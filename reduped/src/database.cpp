#include "reduped/database.hpp"

#include "reduped/fingerprint.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

namespace reduped {
namespace {

class Statement {
public:
    Statement(sqlite3* db, std::string_view sql) : db_(db) {
        if (sqlite3_prepare_v2(db, std::string(sql).c_str(), -1, &stmt_, nullptr) != SQLITE_OK)
            throw std::runtime_error(sqlite3_errmsg(db));
    }
    ~Statement() { if (stmt_) sqlite3_finalize(stmt_); }
    Statement(const Statement&) = delete;
    void text(int index, std::string_view value) {
        if (sqlite3_bind_text(stmt_, index, value.data(), static_cast<int>(value.size()), SQLITE_TRANSIENT) != SQLITE_OK)
            throw std::runtime_error(sqlite3_errmsg(db_));
    }
    void integer(int index, std::int64_t value) {
        if (sqlite3_bind_int64(stmt_, index, value) != SQLITE_OK) throw std::runtime_error(sqlite3_errmsg(db_));
    }
    void real(int index, double value) {
        if (sqlite3_bind_double(stmt_, index, value) != SQLITE_OK) throw std::runtime_error(sqlite3_errmsg(db_));
    }
    void null(int index) { sqlite3_bind_null(stmt_, index); }
    bool row() {
        const int result = sqlite3_step(stmt_);
        if (result == SQLITE_ROW) return true;
        if (result == SQLITE_DONE) return false;
        throw std::runtime_error(sqlite3_errmsg(db_));
    }
    void done() { if (row()) throw std::runtime_error("Statement unexpectedly returned a row"); }
    std::string string(int column) const {
        const auto* value = sqlite3_column_text(stmt_, column);
        return value ? reinterpret_cast<const char*>(value) : std::string{};
    }
    std::int64_t integer(int column) const { return sqlite3_column_int64(stmt_, column); }
    double real(int column) const { return sqlite3_column_double(stmt_, column); }
    bool is_null(int column) const { return sqlite3_column_type(stmt_, column) == SQLITE_NULL; }
    sqlite3_stmt* get() const { return stmt_; }
private:
    sqlite3* db_{};
    sqlite3_stmt* stmt_{};
};

std::string media_name(MediaKind kind) {
    switch (kind) {
        case MediaKind::image: return "image";
        case MediaKind::animated_image: return "animated_image";
        case MediaKind::video: return "video";
        default: return "unknown";
    }
}

MediaKind media_kind(std::string_view name) {
    if (name == "image") return MediaKind::image;
    if (name == "animated_image") return MediaKind::animated_image;
    if (name == "video") return MediaKind::video;
    return MediaKind::unknown;
}

std::string hex64(std::uint64_t value) {
    constexpr char digits[] = "0123456789abcdef";
    std::string out(16, '0');
    for (int i = 15; i >= 0; --i) { out[static_cast<std::size_t>(i)] = digits[value & 15U]; value >>= 4U; }
    return out;
}

std::optional<std::uint64_t> parse64(std::string_view value) {
    if (value.empty()) return std::nullopt;
    std::uint64_t out{};
    const auto [end, error] = std::from_chars(value.data(), value.data()+value.size(), out, 16);
    if (error != std::errc{} || end != value.data()+value.size()) return std::nullopt;
    return out;
}

std::string encode256(const std::optional<Hash256>& hash) {
    if (!hash) return {};
    std::string out;
    for (auto word : *hash) out += hex64(word);
    return out;
}

std::optional<Hash256> decode256(std::string_view value) {
    if (value.size() != 64) return std::nullopt;
    Hash256 result{};
    for (std::size_t i=0;i<4;++i) {
        auto word=parse64(value.substr(i*16,16));
        if (!word) return std::nullopt;
        result[i]=*word;
    }
    return result;
}

template<class Range, class Encoder>
std::string join(const Range& values, Encoder encoder) {
    std::string out;
    bool first=true;
    for (const auto& value : values) { if (!first) out += ','; first=false; out += encoder(value); }
    return out;
}

std::vector<std::uint64_t> decode64_list(std::string_view value) {
    std::vector<std::uint64_t> out;
    for (std::size_t start=0;start<value.size();) {
        const auto end=value.find(',',start);
        const auto part=value.substr(start,end==std::string_view::npos?value.size()-start:end-start);
        if (auto parsed=parse64(part)) out.push_back(*parsed);
        if (end==std::string_view::npos) break;
        start=end+1;
    }
    return out;
}

std::vector<Hash256> decode256_list(std::string_view value) {
    std::vector<Hash256> out;
    for (std::size_t start=0;start<value.size();) {
        const auto end=value.find(',',start);
        const auto part=value.substr(start,end==std::string_view::npos?value.size()-start:end-start);
        if (auto parsed=decode256(part)) out.push_back(*parsed);
        if (end==std::string_view::npos) break;
        start=end+1;
    }
    return out;
}

JobState parse_job(std::string_view state) {
    if(state=="awaiting_remote")return JobState::awaiting_remote;
    if(state=="running")return JobState::running;
    if(state=="retry")return JobState::retry;
    if(state=="complete")return JobState::complete;
    if(state=="cancelled")return JobState::cancelled;
    return JobState::pending;
}

} // namespace

Database::Database(const std::filesystem::path& path) {
    const auto utf8 = path.u8string();
    if (sqlite3_open_v2(reinterpret_cast<const char*>(utf8.c_str()), &db_,
                        SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_FULLMUTEX, nullptr) != SQLITE_OK) {
        const std::string error = db_ ? sqlite3_errmsg(db_) : "Unable to open database";
        if (db_) sqlite3_close(db_);
        db_=nullptr;
        throw std::runtime_error(error);
    }
    try { migrate(); } catch (...) { sqlite3_close(db_); db_=nullptr; throw; }
}

Database::~Database() { if (db_) sqlite3_close(db_); }

void Database::execute(std::string_view sql) const {
    char* error=nullptr;
    if(sqlite3_exec(db_,std::string(sql).c_str(),nullptr,nullptr,&error)!=SQLITE_OK){
        std::string message=error?error:sqlite3_errmsg(db_); if(error)sqlite3_free(error); throw std::runtime_error(message);
    }
}

void Database::transaction(const std::function<void()>& body) const {
    execute("BEGIN IMMEDIATE");
    try { body(); execute("COMMIT"); }
    catch (...) { try { execute("ROLLBACK"); } catch (...) {} throw; }
}

std::string Database::scalar_text(std::string_view sql) const {
    Statement statement(db_,sql); return statement.row()?statement.string(0):std::string{};
}

void Database::migrate() {
    std::lock_guard lock(mutex_);
    execute("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL; PRAGMA busy_timeout=15000;");
    transaction([&]{
        execute(R"SQL(
CREATE TABLE IF NOT EXISTS rd_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rd_assets(
 key TEXT PRIMARY KEY,size INTEGER NOT NULL,etag TEXT NOT NULL,last_modified TEXT NOT NULL,
 object_version TEXT NOT NULL,media_kind TEXT NOT NULL,present INTEGER NOT NULL DEFAULT 1,
 deleted_by_app INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS rd_evidence(
 key TEXT NOT NULL,object_version TEXT NOT NULL,hash_version TEXT NOT NULL,sha256 TEXT NOT NULL,
 phash TEXT,pdq TEXT,pdq_quality INTEGER NOT NULL DEFAULT 0,crop_hashes TEXT NOT NULL DEFAULT '',
 video_hashes TEXT NOT NULL DEFAULT '',width INTEGER NOT NULL DEFAULT 0,height INTEGER NOT NULL DEFAULT 0,
 duration REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(key,object_version,hash_version));
CREATE TABLE IF NOT EXISTS rd_generations(
 id TEXT PRIMARY KEY,state TEXT NOT NULL,inventory_fingerprint TEXT NOT NULL,slider INTEGER NOT NULL,
 matcher_version TEXT NOT NULL,hash_version TEXT NOT NULL,workflow_version TEXT NOT NULL,
 complete INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 certified_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS rd_one_active_generation ON rd_generations(state) WHERE state='certified';
CREATE TABLE IF NOT EXISTS rd_generation_assets(
 generation_id TEXT NOT NULL REFERENCES rd_generations(id) ON DELETE CASCADE,key TEXT NOT NULL,
 object_version TEXT NOT NULL,PRIMARY KEY(generation_id,key));
CREATE TABLE IF NOT EXISTS rd_families(
 generation_id TEXT NOT NULL REFERENCES rd_generations(id) ON DELETE CASCADE,id TEXT NOT NULL,
 survivor_key TEXT NOT NULL,certified INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(generation_id,id));
CREATE TABLE IF NOT EXISTS rd_family_members(
 generation_id TEXT NOT NULL,family_id TEXT NOT NULL,key TEXT NOT NULL,role TEXT NOT NULL,
 priority INTEGER NOT NULL,PRIMARY KEY(generation_id,family_id,key),
 FOREIGN KEY(generation_id,family_id) REFERENCES rd_families(generation_id,id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS rd_pairs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,generation_id TEXT NOT NULL,family_id TEXT NOT NULL,
 left_key TEXT NOT NULL,right_key TEXT NOT NULL,difference REAL NOT NULL,reason TEXT NOT NULL,
 excluded INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 1,
 FOREIGN KEY(generation_id,family_id) REFERENCES rd_families(generation_id,id) ON DELETE CASCADE,
 UNIQUE(generation_id,left_key,right_key));
CREATE INDEX IF NOT EXISTS rd_pairs_queue ON rd_pairs(generation_id,excluded,difference,id);
CREATE TABLE IF NOT EXISTS rd_exact_deletions(
 generation_id TEXT NOT NULL REFERENCES rd_generations(id) ON DELETE CASCADE,survivor_key TEXT NOT NULL,
 deletion_key TEXT NOT NULL,PRIMARY KEY(generation_id,deletion_key));
CREATE TABLE IF NOT EXISTS rd_review_state(
 generation_id TEXT PRIMARY KEY REFERENCES rd_generations(id) ON DELETE CASCADE,position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rd_actions(
 id INTEGER PRIMARY KEY AUTOINCREMENT,generation_id TEXT NOT NULL,family_id TEXT,pair_id INTEGER,
 deleted_key TEXT NOT NULL,protected_key TEXT,source TEXT NOT NULL,state TEXT NOT NULL,
 remote_result TEXT NOT NULL DEFAULT '',index_state TEXT NOT NULL DEFAULT 'not_started',
 error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,completed_at TEXT);
CREATE TABLE IF NOT EXISTS rd_index_cleanup(
 key TEXT PRIMARY KEY,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
 last_error TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS rd_recert_jobs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,generation_id TEXT NOT NULL,family_id TEXT NOT NULL,
 deleted_key TEXT NOT NULL,protected_key TEXT NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 last_error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,completed_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS rd_one_open_recert ON rd_recert_jobs(deleted_key)
 WHERE state IN('awaiting_remote','pending','running','retry');
CREATE TABLE IF NOT EXISTS rd_recert_members(
 job_id INTEGER NOT NULL REFERENCES rd_recert_jobs(id) ON DELETE CASCADE,key TEXT NOT NULL,priority INTEGER NOT NULL,
 PRIMARY KEY(job_id,key),UNIQUE(job_id,priority));
INSERT INTO rd_meta(key,value) VALUES('schema_version','1') ON CONFLICT(key) DO UPDATE SET value='1';
)SQL");
        execute("UPDATE rd_recert_jobs SET state='retry',last_error=CASE WHEN last_error='' THEN 'Application closed during family recertification' ELSE last_error END WHERE state='running';");
    });
    const auto integrity=scalar_text("PRAGMA integrity_check");
    if(integrity!="ok") throw std::runtime_error("Database integrity check failed: "+integrity);
}

Reconciliation Database::reconcile_inventory(std::span<const ObjectRecord> current) {
    std::lock_guard lock(mutex_);
    Reconciliation result;
    std::unordered_map<std::string,ObjectRecord> existing;
    { Statement q(db_,"SELECT key,size,etag,last_modified,media_kind FROM rd_assets WHERE present=1");
      while(q.row()) existing.emplace(q.string(0),ObjectRecord{q.string(0),static_cast<std::uint64_t>(q.integer(1)),q.string(2),q.string(3),media_kind(q.string(4))}); }
    transaction([&]{
        Statement upsert(db_,R"SQL(INSERT INTO rd_assets(key,size,etag,last_modified,object_version,media_kind,present,deleted_by_app)
VALUES(?,?,?,?,?,?,1,0) ON CONFLICT(key) DO UPDATE SET size=excluded.size,etag=excluded.etag,
last_modified=excluded.last_modified,object_version=excluded.object_version,media_kind=excluded.media_kind,present=1,deleted_by_app=0,updated_at=CURRENT_TIMESTAMP)SQL");
        std::unordered_set<std::string> seen;
        for(const auto& object:current){
            if(!seen.insert(object.key).second) throw std::runtime_error("Inventory contains duplicate object key: "+object.key);
            const auto found=existing.find(object.key);
            if(found==existing.end()) result.added.push_back(object);
            else if(object_version(found->second)==object_version(object)) result.unchanged.push_back(object);
            else result.changed.push_back(object);
            upsert.text(1,object.key); upsert.integer(2,static_cast<std::int64_t>(object.size)); upsert.text(3,object.etag);
            upsert.text(4,object.last_modified); upsert.text(5,object_version(object)); upsert.text(6,media_name(object.media_kind)); upsert.done();
            sqlite3_reset(upsert.get()); sqlite3_clear_bindings(upsert.get());
        }
        Statement missing(db_,"UPDATE rd_assets SET present=0,updated_at=CURRENT_TIMESTAMP WHERE key=?");
        for(const auto& [key,object]:existing) if(!seen.contains(key)){
            result.missing.push_back(object); missing.text(1,key); missing.done(); sqlite3_reset(missing.get()); sqlite3_clear_bindings(missing.get());
        }
    });
    return result;
}

std::vector<ObjectRecord> Database::live_assets() const {
    std::lock_guard lock(mutex_); std::vector<ObjectRecord> out;
    Statement q(db_,"SELECT key,size,etag,last_modified,media_kind FROM rd_assets WHERE present=1 ORDER BY key");
    while(q.row()) out.push_back({q.string(0),static_cast<std::uint64_t>(q.integer(1)),q.string(2),q.string(3),media_kind(q.string(4))});
    return out;
}

std::optional<Evidence> Database::evidence_for(std::string_view key,std::string_view version,std::string_view hash_version) const {
    std::lock_guard lock(mutex_);
    Statement q(db_,R"SQL(SELECT sha256,phash,pdq,pdq_quality,crop_hashes,video_hashes,width,height,duration,error
FROM rd_evidence WHERE key=? AND object_version=? AND hash_version=?)SQL");
    q.text(1,key);q.text(2,version);q.text(3,hash_version); if(!q.row())return std::nullopt;
    Evidence e; e.key=std::string(key);e.object_version=std::string(version);e.hash_version=std::string(hash_version);e.sha256=q.string(0);
    e.phash=parse64(q.string(1));e.pdq=decode256(q.string(2));e.pdq_quality=static_cast<int>(q.integer(3));
    e.crop_hashes=decode64_list(q.string(4));e.video_hashes=decode256_list(q.string(5));e.width=static_cast<int>(q.integer(6));
    e.height=static_cast<int>(q.integer(7));e.duration_seconds=q.real(8);e.error=q.string(9);return e;
}

std::vector<Evidence> Database::current_evidence(std::string_view hash_version) const {
    std::lock_guard lock(mutex_);std::vector<Evidence> out;
    Statement q(db_,R"SQL(SELECT e.key,e.object_version,e.sha256,e.phash,e.pdq,e.pdq_quality,e.crop_hashes,e.video_hashes,
e.width,e.height,e.duration,e.error FROM rd_evidence e JOIN rd_assets a ON a.key=e.key AND a.object_version=e.object_version
WHERE a.present=1 AND e.hash_version=? ORDER BY e.key)SQL");q.text(1,hash_version);
    while(q.row()){Evidence e;e.key=q.string(0);e.object_version=q.string(1);e.hash_version=std::string(hash_version);e.sha256=q.string(2);
      e.phash=parse64(q.string(3));e.pdq=decode256(q.string(4));e.pdq_quality=static_cast<int>(q.integer(5));e.crop_hashes=decode64_list(q.string(6));
      e.video_hashes=decode256_list(q.string(7));e.width=static_cast<int>(q.integer(8));e.height=static_cast<int>(q.integer(9));e.duration_seconds=q.real(10);e.error=q.string(11);out.push_back(std::move(e));}
    return out;
}

void Database::save_evidence(const Evidence& e) {
    std::lock_guard lock(mutex_);transaction([&]{Statement q(db_,R"SQL(INSERT INTO rd_evidence(key,object_version,hash_version,sha256,phash,pdq,pdq_quality,crop_hashes,video_hashes,width,height,duration,error)
VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key,object_version,hash_version) DO UPDATE SET sha256=excluded.sha256,phash=excluded.phash,
pdq=excluded.pdq,pdq_quality=excluded.pdq_quality,crop_hashes=excluded.crop_hashes,video_hashes=excluded.video_hashes,width=excluded.width,
height=excluded.height,duration=excluded.duration,error=excluded.error,created_at=CURRENT_TIMESTAMP)SQL");
      q.text(1,e.key);q.text(2,e.object_version);q.text(3,e.hash_version);q.text(4,e.sha256); if(e.phash)q.text(5,hex64(*e.phash));else q.null(5);
      if(e.pdq)q.text(6,encode256(e.pdq));else q.null(6);q.integer(7,e.pdq_quality);q.text(8,join(e.crop_hashes,hex64));
      q.text(9,join(e.video_hashes,[](const Hash256& h){return encode256(h);}));q.integer(10,e.width);q.integer(11,e.height);q.real(12,e.duration_seconds);q.text(13,e.error);q.done();});
}

std::string Database::create_staging(const GenerationIdentity& identity) {
    std::lock_guard lock(mutex_);const std::array<std::string,5> parts{identity.inventory_fingerprint,std::to_string(identity.slider),identity.matcher_version,identity.hash_version,identity.workflow_version};
    auto id=stable_id("generation",parts);transaction([&]{
      Statement del(db_,"DELETE FROM rd_generations WHERE id=? AND state IN('staging','failed')");del.text(1,id);del.done();
      Statement q(db_,"INSERT INTO rd_generations(id,state,inventory_fingerprint,slider,matcher_version,hash_version,workflow_version,complete) VALUES(?,'staging',?,?,?,?,?,0)");
      q.text(1,id);q.text(2,identity.inventory_fingerprint);q.integer(3,identity.slider);q.text(4,identity.matcher_version);q.text(5,identity.hash_version);q.text(6,identity.workflow_version);q.done();
      Statement assets(db_,"INSERT INTO rd_generation_assets(generation_id,key,object_version) SELECT ?,key,object_version FROM rd_assets WHERE present=1");assets.text(1,id);assets.done();});return id;
}

void Database::save_staging_result(std::string_view gid,std::span<const Family> families,std::span<const ReviewPair> pairs,std::span<const ExactDeletion> exact){
    std::lock_guard lock(mutex_);transaction([&]{
      Statement state(db_,"SELECT 1 FROM rd_generations WHERE id=? AND state='staging'");state.text(1,gid);if(!state.row())throw std::runtime_error("Generation is not staging");
      Statement f(db_,"INSERT INTO rd_families(generation_id,id,survivor_key,certified,revision) VALUES(?,?,?,1,1)");
      Statement m(db_,"INSERT INTO rd_family_members(generation_id,family_id,key,role,priority) VALUES(?,?,?,?,?)");
      for(const auto& family:families){f.text(1,gid);f.text(2,family.id);f.text(3,family.survivor);f.done();sqlite3_reset(f.get());sqlite3_clear_bindings(f.get());
        for(std::size_t i=0;i<family.members.size();++i){m.text(1,gid);m.text(2,family.id);m.text(3,family.members[i]);m.text(4,family.members[i]==family.survivor?"survivor":"candidate");m.integer(5,static_cast<std::int64_t>(i));m.done();sqlite3_reset(m.get());sqlite3_clear_bindings(m.get());}}
      Statement p(db_,"INSERT INTO rd_pairs(generation_id,family_id,left_key,right_key,difference,reason,excluded,revision) VALUES(?,?,?,?,?,?,0,1)");
      for(const auto& pair:pairs){p.text(1,gid);p.text(2,pair.family_id);p.text(3,pair.left_key);p.text(4,pair.right_key);p.real(5,pair.difference);p.text(6,pair.reason);p.done();sqlite3_reset(p.get());sqlite3_clear_bindings(p.get());}
      Statement x(db_,"INSERT INTO rd_exact_deletions(generation_id,survivor_key,deletion_key) VALUES(?,?,?)");for(const auto& item:exact){x.text(1,gid);x.text(2,item.survivor_key);x.text(3,item.deletion_key);x.done();sqlite3_reset(x.get());sqlite3_clear_bindings(x.get());}
      Statement done(db_,"UPDATE rd_generations SET complete=1 WHERE id=? AND state='staging'");done.text(1,gid);done.done();
    });
}

void Database::promote(std::string_view gid){std::lock_guard lock(mutex_);transaction([&]{
  Statement verify(db_,"SELECT 1 FROM rd_generations WHERE id=? AND state='staging' AND complete=1");verify.text(1,gid);if(!verify.row())throw std::runtime_error("Incomplete staging generation cannot be promoted");
  Statement roles(db_,R"SQL(SELECT 1 FROM rd_pairs p JOIN rd_families f ON f.generation_id=p.generation_id AND f.id=p.family_id
WHERE p.generation_id=? AND (p.left_key<>f.survivor_key OR p.right_key=f.survivor_key) LIMIT 1)SQL");roles.text(1,gid);if(roles.row())throw std::runtime_error("Staging generation contains contradictory pair orientation");
  Statement duplicate_target(db_,"SELECT 1 FROM rd_pairs WHERE generation_id=? GROUP BY right_key HAVING COUNT(*)>1 LIMIT 1");duplicate_target.text(1,gid);if(duplicate_target.row())throw std::runtime_error("Staging generation repeats a deletion candidate");
  Statement target_survivor(db_,R"SQL(SELECT 1 FROM rd_pairs p JOIN rd_families f ON f.generation_id=p.generation_id AND f.survivor_key=p.right_key
WHERE p.generation_id=? LIMIT 1)SQL");target_survivor.text(1,gid);if(target_survivor.row())throw std::runtime_error("Staging generation assigns contradictory survivor and deletion roles");
  execute("UPDATE rd_generations SET state='inactive' WHERE state='certified'");Statement q(db_,"UPDATE rd_generations SET state='certified',certified_at=CURRENT_TIMESTAMP WHERE id=?");q.text(1,gid);q.done();
  Statement state(db_,"INSERT OR IGNORE INTO rd_review_state(generation_id,position) VALUES(?,0)");state.text(1,gid);state.done();});}

void Database::fail_staging(std::string_view gid,std::string_view error){std::lock_guard lock(mutex_);transaction([&]{Statement q(db_,"UPDATE rd_generations SET state='failed',error=? WHERE id=? AND state='staging'");q.text(1,error.substr(0,1000));q.text(2,gid);q.done();});}

std::optional<GenerationSnapshot> Database::active_generation() const {
 std::lock_guard lock(mutex_);Statement g(db_,"SELECT id,state,inventory_fingerprint,slider,matcher_version,hash_version,workflow_version FROM rd_generations WHERE state='certified' AND complete=1");if(!g.row())return std::nullopt;
 GenerationSnapshot s;s.id=g.string(0);s.state=GenerationState::certified;s.identity={g.string(2),static_cast<int>(g.integer(3)),g.string(4),g.string(5),g.string(6)};
 Statement p(db_,R"SQL(SELECT p.id,p.family_id,p.left_key,p.right_key,p.difference,p.reason,p.excluded,p.revision FROM rd_pairs p
JOIN rd_families f ON f.generation_id=p.generation_id AND f.id=p.family_id WHERE p.generation_id=? AND f.certified=1 ORDER BY p.difference,p.id)SQL");p.text(1,s.id);
 while(p.row())s.pairs.push_back({p.integer(0),s.id,p.string(1),p.string(2),p.string(3),p.real(4),p.string(5),p.integer(6)!=0,static_cast<std::uint64_t>(p.integer(7))});
 Statement x(db_,"SELECT survivor_key,deletion_key FROM rd_exact_deletions WHERE generation_id=? ORDER BY deletion_key");x.text(1,s.id);while(x.row())s.exact_deletions.push_back({x.string(0),x.string(1)});
 Statement r(db_,"SELECT position FROM rd_review_state WHERE generation_id=?");r.text(1,s.id);if(r.row())s.review_position=static_cast<std::size_t>(std::max<std::int64_t>(0,r.integer(0)));return s;
}

bool Database::identity_matches(const GenerationIdentity& identity) const {auto active=active_generation();return active&&active->identity.inventory_fingerprint==identity.inventory_fingerprint&&active->identity.slider==identity.slider&&active->identity.matcher_version==identity.matcher_version&&active->identity.hash_version==identity.hash_version&&active->identity.workflow_version==identity.workflow_version;}

void Database::save_review_position(std::string_view gid,std::size_t position){std::lock_guard lock(mutex_);transaction([&]{Statement q(db_,"INSERT INTO rd_review_state(generation_id,position) VALUES(?,?) ON CONFLICT(generation_id) DO UPDATE SET position=excluded.position");q.text(1,gid);q.integer(2,static_cast<std::int64_t>(position));q.done();});}

bool Database::rendered_pair_is_current(const RenderedPairToken& t) const {std::lock_guard lock(mutex_);Statement q(db_,R"SQL(SELECT 1 FROM rd_pairs p JOIN rd_families f ON f.generation_id=p.generation_id AND f.id=p.family_id JOIN rd_generations g ON g.id=p.generation_id
WHERE p.id=? AND p.generation_id=? AND p.family_id=? AND p.left_key=? AND p.right_key=? AND p.revision=? AND f.certified=1 AND g.state='certified')SQL");q.integer(1,t.pair_id);q.text(2,t.generation_id);q.text(3,t.family_id);q.text(4,t.left_key);q.text(5,t.right_key);q.integer(6,static_cast<std::int64_t>(t.revision));return q.row();}

bool Database::family_is_certified(std::string_view gid,std::string_view fid) const {std::lock_guard lock(mutex_);Statement q(db_,"SELECT 1 FROM rd_families f JOIN rd_generations g ON g.id=f.generation_id WHERE f.generation_id=? AND f.id=? AND f.certified=1 AND g.state='certified'");q.text(1,gid);q.text(2,fid);return q.row();}

bool Database::exclude_pair(const RenderedPairToken& t){std::lock_guard lock(mutex_);if(!rendered_pair_is_current(t))return false;transaction([&]{Statement q(db_,"UPDATE rd_pairs SET excluded=1,revision=revision+1 WHERE id=? AND generation_id=? AND revision=?");q.integer(1,t.pair_id);q.text(2,t.generation_id);q.integer(3,static_cast<std::int64_t>(t.revision));q.done();});return true;}

DeletionIntent Database::prepare_single_deletion(const RenderedPairToken& t,std::string_view selected,std::string_view protected_key){
 std::lock_guard lock(mutex_);if(!rendered_pair_is_current(t))throw std::runtime_error("The visible pair changed before the deletion click was processed");
 if(!((selected==t.left_key&&protected_key==t.right_key)||(selected==t.right_key&&protected_key==t.left_key)))throw std::runtime_error("Deletion side does not match the rendered pair");
 DeletionIntent result;transaction([&]{
  Statement existing(db_,R"SQL(SELECT a.id,j.id,COALESCE(j.protected_key,a.protected_key,'') FROM rd_actions a
LEFT JOIN rd_recert_jobs j ON j.deleted_key=a.deleted_key AND j.state='awaiting_remote'
WHERE a.generation_id=? AND a.deleted_key=? AND a.state='prepared' AND a.source='single' ORDER BY a.id LIMIT 1)SQL");
  existing.text(1,t.generation_id);existing.text(2,selected);if(existing.row()){if(existing.string(2)!=protected_key)throw std::runtime_error("Unfinished deletion has a different protected partner");result.action_id=existing.integer(0);if(!existing.is_null(1))result.recertification_job_id=existing.integer(1);return;}
  Statement included(db_,"SELECT 1 FROM rd_pairs WHERE id=? AND generation_id=? AND excluded=0");included.integer(1,t.pair_id);included.text(2,t.generation_id);if(!included.row())throw std::runtime_error("Excluded pair is not actionable");
  Statement live(db_,"SELECT 1 FROM rd_assets WHERE key=? AND present=1 AND deleted_by_app=0");live.text(1,selected);if(!live.row())throw std::runtime_error("Selected object is no longer present");
  Statement survivor(db_,"SELECT survivor_key FROM rd_families WHERE generation_id=? AND id=? AND certified=1");survivor.text(1,t.generation_id);survivor.text(2,t.family_id);if(!survivor.row())throw std::runtime_error("Family is no longer certified");
  if(survivor.string(0)==selected){
    Statement members(db_,"SELECT key FROM rd_family_members WHERE generation_id=? AND family_id=? AND key<>? ORDER BY CASE WHEN key=? THEN 0 ELSE 1 END,priority");members.text(1,t.generation_id);members.text(2,t.family_id);members.text(3,selected);members.text(4,protected_key);std::vector<std::string> keys;while(members.row())keys.push_back(members.string(0));
    Statement job(db_,"INSERT INTO rd_recert_jobs(generation_id,family_id,deleted_key,protected_key,state) VALUES(?,?,?,?,'awaiting_remote')");job.text(1,t.generation_id);job.text(2,t.family_id);job.text(3,selected);job.text(4,protected_key);job.done();result.recertification_job_id=sqlite3_last_insert_rowid(db_);
    Statement jm(db_,"INSERT INTO rd_recert_members(job_id,key,priority) VALUES(?,?,?)");for(std::size_t i=0;i<keys.size();++i){jm.integer(1,*result.recertification_job_id);jm.text(2,keys[i]);jm.integer(3,static_cast<std::int64_t>(i));jm.done();sqlite3_reset(jm.get());sqlite3_clear_bindings(jm.get());}
  }
  Statement action(db_,"INSERT INTO rd_actions(generation_id,family_id,pair_id,deleted_key,protected_key,source,state) VALUES(?,?,?,?,?,'single','prepared')");action.text(1,t.generation_id);action.text(2,t.family_id);action.integer(3,t.pair_id);action.text(4,selected);action.text(5,protected_key);action.done();result.action_id=sqlite3_last_insert_rowid(db_);
 });return result;
}

DeletionIntent Database::prepare_batch_deletion(std::string_view gid,std::string_view selected,std::string_view protected_key,std::string_view source){
 std::lock_guard lock(mutex_);if(source!="visual_nuke"&&source!="sha_nuke")throw std::runtime_error("Unknown batch deletion source");
 DeletionIntent result;transaction([&]{
  Statement generation(db_,"SELECT 1 FROM rd_generations WHERE id=? AND state='certified' AND complete=1");generation.text(1,gid);if(!generation.row())throw std::runtime_error("Batch deletion requires the active certified generation");
  bool allowed=false;
  if(source=="visual_nuke"){Statement q(db_,R"SQL(SELECT 1 FROM rd_pairs p JOIN rd_families f ON f.generation_id=p.generation_id AND f.id=p.family_id
WHERE p.generation_id=? AND p.right_key=? AND f.survivor_key=? AND p.excluded=0 AND f.certified=1)SQL");q.text(1,gid);q.text(2,selected);q.text(3,protected_key);allowed=q.row();}
  else{Statement q(db_,"SELECT 1 FROM rd_exact_deletions WHERE generation_id=? AND deletion_key=? AND survivor_key=?");q.text(1,gid);q.text(2,selected);q.text(3,protected_key);allowed=q.row();}
  if(!allowed)throw std::runtime_error("Batch deletion target is no longer in the certified plan");
  Statement live(db_,"SELECT 1 FROM rd_assets WHERE key=? AND present=1 AND deleted_by_app=0");live.text(1,selected);if(!live.row())throw std::runtime_error("Batch target is no longer present");
  Statement action(db_,"INSERT INTO rd_actions(generation_id,deleted_key,protected_key,source,state) VALUES(?,?,?,?,'prepared')");action.text(1,gid);action.text(2,selected);action.text(3,protected_key);action.text(4,source);action.done();result.action_id=sqlite3_last_insert_rowid(db_);
 });return result;
}

std::vector<PreparedAction> Database::prepared_actions() const{std::lock_guard lock(mutex_);std::vector<PreparedAction> out;Statement q(db_,R"SQL(SELECT a.id,a.generation_id,a.deleted_key,COALESCE(a.protected_key,''),a.source,j.id
FROM rd_actions a LEFT JOIN rd_recert_jobs j ON j.deleted_key=a.deleted_key AND j.state='awaiting_remote' WHERE a.state='prepared' ORDER BY a.id)SQL");while(q.row()){PreparedAction a{q.integer(0),q.string(1),q.string(2),q.string(3),q.string(4),std::nullopt};if(!q.is_null(5))a.recertification_job_id=q.integer(5);out.push_back(std::move(a));}return out;}

void Database::deletion_remote_failed(std::int64_t action_id,std::string_view error){std::lock_guard lock(mutex_);transaction([&]{Statement a(db_,"UPDATE rd_actions SET state='failed',remote_result='failed',error=?,completed_at=CURRENT_TIMESTAMP WHERE id=? AND state='prepared'");a.text(1,error.substr(0,1000));a.integer(2,action_id);a.done();Statement j(db_,"UPDATE rd_recert_jobs SET state='cancelled',last_error=?,completed_at=CURRENT_TIMESTAMP WHERE id=(SELECT id FROM rd_recert_jobs WHERE deleted_key=(SELECT deleted_key FROM rd_actions WHERE id=?) AND state='awaiting_remote')");j.text(1,error.substr(0,1000));j.integer(2,action_id);j.done();});}

void Database::deletion_remote_succeeded(std::int64_t action_id,std::string_view deleted,std::optional<std::int64_t> job_id){std::lock_guard lock(mutex_);transaction([&]{
 Statement a(db_,"UPDATE rd_actions SET state='complete',remote_result='deleted',index_state='pending',completed_at=CURRENT_TIMESTAMP WHERE id=? AND state='prepared' AND deleted_key=?");a.integer(1,action_id);a.text(2,deleted);a.done();if(sqlite3_changes(db_)!=1)throw std::runtime_error("Deletion action is stale or already finalized");
 Statement asset(db_,"UPDATE rd_assets SET present=0,deleted_by_app=1,updated_at=CURRENT_TIMESTAMP WHERE key=?");asset.text(1,deleted);asset.done();
 Statement cleanup(db_,"INSERT INTO rd_index_cleanup(key,state) VALUES(?,'pending') ON CONFLICT(key) DO UPDATE SET state='pending',updated_at=CURRENT_TIMESTAMP");cleanup.text(1,deleted);cleanup.done();
 Statement exact(db_,"DELETE FROM rd_exact_deletions WHERE deletion_key=? OR survivor_key=?");exact.text(1,deleted);exact.text(2,deleted);exact.done();
 if(job_id){Statement info(db_,"SELECT generation_id,family_id FROM rd_recert_jobs WHERE id=? AND state='awaiting_remote'");info.integer(1,*job_id);if(!info.row())throw std::runtime_error("Recertification intent was not preserved");const auto gid=info.string(0),fid=info.string(1);
   Statement hide(db_,"UPDATE rd_families SET certified=0,revision=revision+1 WHERE generation_id=? AND id=?");hide.text(1,gid);hide.text(2,fid);hide.done();Statement rows(db_,"DELETE FROM rd_pairs WHERE generation_id=? AND family_id=?");rows.text(1,gid);rows.text(2,fid);rows.done();Statement activate(db_,"UPDATE rd_recert_jobs SET state='pending' WHERE id=?");activate.integer(1,*job_id);activate.done();
 } else {Statement rows(db_,"DELETE FROM rd_pairs WHERE generation_id=(SELECT generation_id FROM rd_actions WHERE id=?) AND (left_key=? OR right_key=?)");rows.integer(1,action_id);rows.text(2,deleted);rows.text(3,deleted);rows.done();}
 });}

std::vector<RecertificationJob> Database::recoverable_recertification_jobs(){std::lock_guard lock(mutex_);execute("UPDATE rd_recert_jobs SET state='retry',last_error=CASE WHEN last_error='' THEN 'Application closed during family recertification' ELSE last_error END WHERE state='running'");std::vector<RecertificationJob> out;Statement q(db_,"SELECT id,generation_id,family_id,deleted_key,protected_key,state,attempts,last_error FROM rd_recert_jobs WHERE state IN('pending','retry') ORDER BY id");while(q.row()){RecertificationJob j{q.integer(0),q.string(1),q.string(2),q.string(3),q.string(4),{},parse_job(q.string(5)),static_cast<int>(q.integer(6)),q.string(7)};Statement m(db_,"SELECT key FROM rd_recert_members WHERE job_id=? ORDER BY priority");m.integer(1,j.id);while(m.row())j.priority_keys.push_back(m.string(0));out.push_back(std::move(j));}return out;}

bool Database::claim_recertification(std::int64_t id){std::lock_guard lock(mutex_);transaction([&]{Statement q(db_,"UPDATE rd_recert_jobs SET state='running',attempts=attempts+1,last_error='' WHERE id=? AND state IN('pending','retry')");q.integer(1,id);q.done();});return sqlite3_changes(db_)==1;}
void Database::retry_recertification(std::int64_t id,std::string_view error){std::lock_guard lock(mutex_);transaction([&]{Statement q(db_,"UPDATE rd_recert_jobs SET state='retry',last_error=? WHERE id=? AND state='running'");q.text(1,error.substr(0,1000));q.integer(2,id);q.done();});}

void Database::complete_recertification(std::int64_t id,std::span<const Family> families,std::span<const ReviewPair> pairs){std::lock_guard lock(mutex_);transaction([&]{Statement job(db_,"SELECT generation_id,family_id FROM rd_recert_jobs WHERE id=? AND state='running'");job.integer(1,id);if(!job.row())throw std::runtime_error("Recertification job is not exclusively claimed");const auto gid=job.string(0),old=job.string(1);
 Statement del(db_,"DELETE FROM rd_families WHERE generation_id=? AND id=?");del.text(1,gid);del.text(2,old);del.done();
 Statement f(db_,"INSERT INTO rd_families(generation_id,id,survivor_key,certified,revision) VALUES(?,?,?,1,1)");Statement m(db_,"INSERT INTO rd_family_members(generation_id,family_id,key,role,priority) VALUES(?,?,?,?,?)");for(const auto& family:families){f.text(1,gid);f.text(2,family.id);f.text(3,family.survivor);f.done();sqlite3_reset(f.get());sqlite3_clear_bindings(f.get());for(std::size_t i=0;i<family.members.size();++i){m.text(1,gid);m.text(2,family.id);m.text(3,family.members[i]);m.text(4,family.members[i]==family.survivor?"survivor":"candidate");m.integer(5,static_cast<std::int64_t>(i));m.done();sqlite3_reset(m.get());sqlite3_clear_bindings(m.get());}}
 Statement p(db_,"INSERT INTO rd_pairs(generation_id,family_id,left_key,right_key,difference,reason,excluded,revision) VALUES(?,?,?,?,?,?,0,1)");for(const auto& pair:pairs){p.text(1,gid);p.text(2,pair.family_id);p.text(3,pair.left_key);p.text(4,pair.right_key);p.real(5,pair.difference);p.text(6,pair.reason);p.done();sqlite3_reset(p.get());sqlite3_clear_bindings(p.get());}
 Statement done(db_,"UPDATE rd_recert_jobs SET state='complete',completed_at=CURRENT_TIMESTAMP WHERE id=? AND state='running'");done.integer(1,id);done.done();});}

std::vector<std::string> Database::pending_index_cleanup() const{std::lock_guard lock(mutex_);std::vector<std::string> out;Statement q(db_,"SELECT key FROM rd_index_cleanup WHERE state IN('pending','retry') ORDER BY updated_at");while(q.row())out.push_back(q.string(0));return out;}
void Database::complete_index_cleanup(std::string_view key){std::lock_guard lock(mutex_);transaction([&]{Statement q(db_,"DELETE FROM rd_index_cleanup WHERE key=?");q.text(1,key);q.done();Statement a(db_,"UPDATE rd_actions SET index_state='complete' WHERE deleted_key=? AND remote_result='deleted'");a.text(1,key);a.done();});}
void Database::fail_index_cleanup(std::string_view key,std::string_view error){std::lock_guard lock(mutex_);transaction([&]{Statement q(db_,"UPDATE rd_index_cleanup SET state='retry',attempts=attempts+1,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE key=?");q.text(1,error.substr(0,1000));q.text(2,key);q.done();Statement a(db_,"UPDATE rd_actions SET index_state='retry',error=? WHERE deleted_key=? AND remote_result='deleted'");a.text(1,error.substr(0,1000));a.text(2,key);a.done();});}

std::vector<std::string> Database::visual_nuke_plan(std::string_view gid) const{std::lock_guard lock(mutex_);std::vector<std::string> out;Statement validate(db_,R"SQL(SELECT 1 FROM rd_pairs p JOIN rd_families f ON f.generation_id=p.generation_id AND f.id=p.family_id
WHERE p.generation_id=? AND p.excluded=0 AND f.certified=1 GROUP BY p.right_key HAVING SUM(CASE WHEN p.left_key=p.right_key THEN 1 ELSE 0 END)>0 OR COUNT(DISTINCT f.survivor_key)>1)SQL");validate.text(1,gid);if(validate.row())throw std::runtime_error("NUKE plan contains contradictory object roles");Statement q(db_,R"SQL(SELECT DISTINCT p.right_key FROM rd_pairs p JOIN rd_families f ON f.generation_id=p.generation_id AND f.id=p.family_id JOIN rd_generations g ON g.id=p.generation_id
WHERE p.generation_id=? AND p.excluded=0 AND f.certified=1 AND p.right_key<>f.survivor_key AND g.state='certified' ORDER BY p.right_key)SQL");q.text(1,gid);while(q.row())out.push_back(q.string(0));return out;}
std::vector<std::string> Database::exact_nuke_plan(std::string_view gid) const{std::lock_guard lock(mutex_);std::vector<std::string> out;Statement q(db_,"SELECT e.deletion_key FROM rd_exact_deletions e JOIN rd_generations g ON g.id=e.generation_id WHERE e.generation_id=? AND g.state='certified' ORDER BY e.deletion_key");q.text(1,gid);while(q.row())out.push_back(q.string(0));return out;}
std::vector<ReviewPair> Database::family_pairs(std::string_view gid,std::string_view fid) const{std::lock_guard lock(mutex_);std::vector<ReviewPair> out;Statement q(db_,"SELECT id,left_key,right_key,difference,reason,excluded,revision FROM rd_pairs WHERE generation_id=? AND family_id=? ORDER BY difference,id");q.text(1,gid);q.text(2,fid);while(q.row())out.push_back({q.integer(0),std::string(gid),std::string(fid),q.string(1),q.string(2),q.real(3),q.string(4),q.integer(5)!=0,static_cast<std::uint64_t>(q.integer(6))});return out;}

} // namespace reduped
