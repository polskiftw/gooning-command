#include "reduped/r2_winhttp.hpp"

#include "reduped/fingerprint.hpp"

#include <windows.h>
#include <bcrypt.h>
#include <winhttp.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cstdio>
#include <iomanip>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>

namespace reduped {
namespace {

struct Handle {
    HINTERNET value{};
    Handle()=default;explicit Handle(HINTERNET h):value(h){}
    ~Handle(){if(value)WinHttpCloseHandle(value);}
    Handle(const Handle&)=delete;Handle& operator=(const Handle&)=delete;
};

std::wstring wide(std::string_view text){if(text.empty())return {};const int size=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),nullptr,0);if(size<=0)throw std::runtime_error("Invalid UTF-8 in service configuration");std::wstring out(static_cast<std::size_t>(size),L'\0');MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),out.data(),size);return out;}
std::string utf8(std::wstring_view text){if(text.empty())return {};const int size=WideCharToMultiByte(CP_UTF8,0,text.data(),static_cast<int>(text.size()),nullptr,0,nullptr,nullptr);std::string out(static_cast<std::size_t>(size),'\0');WideCharToMultiByte(CP_UTF8,0,text.data(),static_cast<int>(text.size()),out.data(),size,nullptr,nullptr);return out;}

std::string last_error(std::string_view operation){return std::string(operation)+" failed with system error "+std::to_string(GetLastError());}
bool unreserved(unsigned char c){return std::isalnum(c)||c=='-'||c=='_'||c=='.'||c=='~';}
std::string encode(std::string_view input,bool preserve_slash=false){constexpr char digits[]="0123456789ABCDEF";std::string out;for(unsigned char c:input){if(unreserved(c)||(preserve_slash&&c=='/'))out.push_back(static_cast<char>(c));else{out.push_back('%');out.push_back(digits[c>>4]);out.push_back(digits[c&15]);}}return out;}

std::vector<std::uint8_t> hmac(std::span<const std::uint8_t> key,std::string_view data){
 BCRYPT_ALG_HANDLE algorithm{};BCRYPT_HASH_HANDLE hash{};DWORD object_size{},written{},hash_size{};
 if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,BCRYPT_ALG_HANDLE_HMAC_FLAG)<0)throw std::runtime_error("Unable to initialize request signing");
 auto close_algorithm=std::unique_ptr<void,decltype([](void* p){if(p)BCryptCloseAlgorithmProvider(static_cast<BCRYPT_ALG_HANDLE>(p),0);})>(algorithm,{});
 BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&object_size),sizeof(object_size),&written,0);
 BCryptGetProperty(algorithm,BCRYPT_HASH_LENGTH,reinterpret_cast<PUCHAR>(&hash_size),sizeof(hash_size),&written,0);
 std::vector<std::uint8_t> object(object_size),result(hash_size);
 if(BCryptCreateHash(algorithm,&hash,object.data(),object_size,const_cast<PUCHAR>(key.data()),static_cast<ULONG>(key.size()),0)<0)throw std::runtime_error("Unable to create request signature");
 auto close_hash=std::unique_ptr<void,decltype([](void* p){if(p)BCryptDestroyHash(static_cast<BCRYPT_HASH_HANDLE>(p));})>(hash,{});
 if(BCryptHashData(hash,reinterpret_cast<PUCHAR>(const_cast<char*>(data.data())),static_cast<ULONG>(data.size()),0)<0||BCryptFinishHash(hash,result.data(),hash_size,0)<0)throw std::runtime_error("Unable to sign request");return result;
}

std::string hex(std::span<const std::uint8_t> bytes){constexpr char d[]="0123456789abcdef";std::string out;out.reserve(bytes.size()*2);for(auto b:bytes){out.push_back(d[b>>4]);out.push_back(d[b&15]);}return out;}

std::string xml_decode(std::string value){const std::array pairs{std::pair{"&amp;","&"},std::pair{"&lt;","<"},std::pair{"&gt;",">"},std::pair{"&quot;","\""},std::pair{"&apos;","'"}};for(const auto& [from,to]:pairs)for(std::size_t at=0;(at=value.find(from,at))!=std::string::npos;at+=std::char_traits<char>::length(to))value.replace(at,std::char_traits<char>::length(from),to);return value;}
std::string xml_value(std::string_view xml,std::string_view tag){const std::string open="<"+std::string(tag)+">",close="</"+std::string(tag)+">";auto begin=xml.find(open);if(begin==std::string_view::npos)return {};begin+=open.size();auto end=xml.find(close,begin);return end==std::string_view::npos?std::string{}:xml_decode(std::string(xml.substr(begin,end-begin)));}

MediaKind kind_for(std::string key){std::transform(key.begin(),key.end(),key.begin(),[](unsigned char c){return static_cast<char>(std::tolower(c));});const auto dot=key.rfind('.');const auto ext=dot==std::string::npos?std::string{}:key.substr(dot+1);if(ext=="gif"||ext=="apng")return MediaKind::animated_image;if(ext=="mp4"||ext=="m4v"||ext=="mov"||ext=="webm"||ext=="mkv"||ext=="avi")return MediaKind::video;if(ext=="jpg"||ext=="jpeg"||ext=="png"||ext=="webp"||ext=="bmp"||ext=="tif"||ext=="tiff"||ext=="heic"||ext=="avif")return MediaKind::image;return MediaKind::unknown;}

struct Response{DWORD status{};std::vector<std::uint8_t> body;std::string etag;};

} // namespace

struct WinHttpObjectStore::Impl{
 Config config;std::wstring host;std::wstring base_path;INTERNET_PORT port{};bool secure{};Handle session;Handle connection;
 explicit Impl(const Config& c):config(c){
  const auto endpoint=wide(config.endpoint);URL_COMPONENTS parts{};parts.dwStructSize=sizeof(parts);parts.dwHostNameLength=static_cast<DWORD>(-1);parts.dwUrlPathLength=static_cast<DWORD>(-1);
  if(!WinHttpCrackUrl(endpoint.c_str(),static_cast<DWORD>(endpoint.size()),0,&parts))throw std::runtime_error("ENDPOINT is not a valid absolute service address");
  host.assign(parts.lpszHostName,parts.dwHostNameLength);base_path.assign(parts.lpszUrlPath,parts.dwUrlPathLength);while(base_path.size()>1&&base_path.back()==L'/')base_path.pop_back();port=parts.nPort;secure=parts.nScheme==INTERNET_SCHEME_HTTPS;
  session=Handle(WinHttpOpen(L"Reduped/1",WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,WINHTTP_NO_PROXY_NAME,WINHTTP_NO_PROXY_BYPASS,0));if(!session.value)throw std::runtime_error(last_error("Network session creation"));
  WinHttpSetTimeouts(session.value,10000,10000,30000,30000);
  connection=Handle(WinHttpConnect(session.value,host.c_str(),port,0));if(!connection.value)throw std::runtime_error(last_error("Service connection"));
 }

 std::string canonical_path(std::string_view key)const{std::string path=utf8(base_path);if(path.empty()||path.back()!='/')path+='/';path+=encode(config.bucket);if(!key.empty()){path+='/';path+=encode(key,true);}return path;}

 Response request(std::wstring_view method,std::string_view key,std::vector<std::pair<std::string,std::string>> query={},std::span<const std::uint8_t> body={},std::vector<std::pair<std::string,std::string>> headers={}){
  std::sort(query.begin(),query.end());std::string canonical_query;for(const auto& [name,value]:query){if(!canonical_query.empty())canonical_query+='&';canonical_query+=encode(name)+"="+encode(value);}
  const auto path=canonical_path(key);std::string target=path;if(!canonical_query.empty())target+="?"+canonical_query;
  SYSTEMTIME time{};GetSystemTime(&time);char date[17],day[9];std::snprintf(date,sizeof(date),"%04u%02u%02uT%02u%02u%02uZ",time.wYear,time.wMonth,time.wDay,time.wHour,time.wMinute,time.wSecond);std::snprintf(day,sizeof(day),"%04u%02u%02u",time.wYear,time.wMonth,time.wDay);
  const auto payload_hash=sha256_hex(body);const auto host_text=utf8(host)+(port!=INTERNET_DEFAULT_HTTPS_PORT&&port!=INTERNET_DEFAULT_HTTP_PORT?":"+std::to_string(port):"");
  const std::string canonical_headers="host:"+host_text+"\n"+"x-amz-content-sha256:"+payload_hash+"\n"+"x-amz-date:"+date+"\n";
  const std::string signed_headers="host;x-amz-content-sha256;x-amz-date";
  const std::string canonical_request=utf8(method)+"\n"+path+"\n"+canonical_query+"\n"+canonical_headers+"\n"+signed_headers+"\n"+payload_hash;
  const std::string scope=std::string(day)+"/"+config.region+"/s3/aws4_request";const std::string to_sign="AWS4-HMAC-SHA256\n"+std::string(date)+"\n"+scope+"\n"+sha256_hex(canonical_request);
  const std::string seed="AWS4"+config.secret_access_key;auto date_key=hmac(std::span(reinterpret_cast<const std::uint8_t*>(seed.data()),seed.size()),day);auto region_key=hmac(date_key,config.region);auto service_key=hmac(region_key,"s3");auto signing_key=hmac(service_key,"aws4_request");auto signature=hmac(signing_key,to_sign);
  const std::string authorization="AWS4-HMAC-SHA256 Credential="+config.access_key_id+"/"+scope+", SignedHeaders="+signed_headers+", Signature="+hex(signature);
  DWORD flags=secure?WINHTTP_FLAG_SECURE:0;Handle request(WinHttpOpenRequest(connection.value,std::wstring(method).c_str(),wide(target).c_str(),nullptr,WINHTTP_NO_REFERER,WINHTTP_DEFAULT_ACCEPT_TYPES,flags));if(!request.value)throw std::runtime_error(last_error("Request creation"));
  std::wstring request_headers=L"x-amz-content-sha256: "+wide(payload_hash)+L"\r\nx-amz-date: "+wide(date)+L"\r\nAuthorization: "+wide(authorization)+L"\r\n";for(const auto& [name,value]:headers)request_headers+=wide(name)+L": "+wide(value)+L"\r\n";
  if(!WinHttpSendRequest(request.value,request_headers.c_str(),static_cast<DWORD>(request_headers.size()),body.empty()?WINHTTP_NO_REQUEST_DATA:const_cast<std::uint8_t*>(body.data()),static_cast<DWORD>(body.size()),static_cast<DWORD>(body.size()),0)||!WinHttpReceiveResponse(request.value,nullptr))throw std::runtime_error(last_error("Service request"));
  Response response;DWORD size=sizeof(response.status);WinHttpQueryHeaders(request.value,WINHTTP_QUERY_STATUS_CODE|WINHTTP_QUERY_FLAG_NUMBER,WINHTTP_HEADER_NAME_BY_INDEX,&response.status,&size,WINHTTP_NO_HEADER_INDEX);
  wchar_t etag[512];size=sizeof(etag);if(WinHttpQueryHeaders(request.value,WINHTTP_QUERY_ETAG,WINHTTP_HEADER_NAME_BY_INDEX,etag,&size,WINHTTP_NO_HEADER_INDEX))response.etag=utf8(std::wstring_view(etag,size/sizeof(wchar_t)-1));
  while(true){DWORD available{};if(!WinHttpQueryDataAvailable(request.value,&available))throw std::runtime_error(last_error("Response read"));if(!available)break;const auto offset=response.body.size();response.body.resize(offset+available);DWORD received{};if(!WinHttpReadData(request.value,response.body.data()+offset,available,&received))throw std::runtime_error(last_error("Response read"));response.body.resize(offset+received);}
  return response;
 }

 Response require(std::wstring_view method,std::string_view key,std::vector<std::pair<std::string,std::string>> query={},std::span<const std::uint8_t> body={},std::vector<std::pair<std::string,std::string>> headers={}){auto response=request(method,key,std::move(query),body,std::move(headers));if(response.status<200||response.status>=300)throw std::runtime_error("Object service returned status "+std::to_string(response.status));return response;}
};

WinHttpObjectStore::WinHttpObjectStore(const Config& config):impl_(std::make_unique<Impl>(config)){}
WinHttpObjectStore::~WinHttpObjectStore()=default;

std::vector<ObjectRecord> WinHttpObjectStore::list_inventory(std::atomic_bool& cancelled){std::vector<ObjectRecord> out;std::string token;do{if(cancelled.load())break;std::vector<std::pair<std::string,std::string>> query{{"list-type","2"},{"prefix",impl_->config.prefix}};if(!token.empty())query.emplace_back("continuation-token",token);auto response=impl_->require(L"GET","",std::move(query));std::string xml(response.body.begin(),response.body.end());std::size_t at=0;while((at=xml.find("<Contents>",at))!=std::string::npos){const auto end=xml.find("</Contents>",at);if(end==std::string::npos)break;const auto block=std::string_view(xml).substr(at,end+11-at);ObjectRecord object;object.key=xml_value(block,"Key");const auto size=xml_value(block,"Size");object.size=size.empty()?0:std::stoull(size);object.etag=xml_value(block,"ETag");if(object.etag.size()>=2&&object.etag.front()=='\"'&&object.etag.back()=='\"')object.etag=object.etag.substr(1,object.etag.size()-2);object.last_modified=xml_value(block,"LastModified");object.media_kind=kind_for(object.key);if(!object.key.empty()&&object.size>0&&object.media_kind!=MediaKind::unknown)out.push_back(std::move(object));at=end+11;}token=xml_value(xml,"NextContinuationToken");const auto truncated=xml_value(xml,"IsTruncated");if(truncated!="true")token.clear();}while(!token.empty());return out;}

std::vector<std::uint8_t> WinHttpObjectStore::download(std::string_view key,std::atomic_bool& cancelled){if(cancelled.load())return {};return impl_->require(L"GET",key).body;}
DeleteResult WinHttpObjectStore::delete_object(std::string_view key){auto response=impl_->request(L"DELETE",key);if(response.status==404)return DeleteResult::not_found;if(response.status<200||response.status>=300)throw std::runtime_error("Object deletion returned status "+std::to_string(response.status));return DeleteResult::deleted;}

void WinHttpObjectStore::remove_from_index(std::string_view index_key,std::string_view deleted_key){
 for(int attempt=0;attempt<8;++attempt){auto current=impl_->request(L"GET",index_key);if(current.status==404)return;if(current.status<200||current.status>=300)throw std::runtime_error("Index read returned status "+std::to_string(current.status));
  auto document=nlohmann::json::parse(current.body.begin(),current.body.end());nlohmann::json* items=nullptr;if(document.is_array())items=&document;else if(document.is_object()&&document.contains("items")&&document["items"].is_array())items=&document["items"];else throw std::runtime_error("Index has an unsupported JSON structure");
  const auto before=items->size();items->erase(std::remove_if(items->begin(),items->end(),[&](const auto& item){return item.is_object()&&item.value("key",std::string{})==deleted_key;}),items->end());if(items->size()==before)return;
  if(document.is_object()){document["count"]=items->size();document["generated_at"]=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count();}
  const auto encoded=document.dump();const std::span body(reinterpret_cast<const std::uint8_t*>(encoded.data()),encoded.size());auto response=impl_->request(L"PUT",index_key,{},body,{{"Content-Type","application/json"},{"Cache-Control","no-cache"},{"If-Match",current.etag}});if(response.status>=200&&response.status<300)return;if(response.status!=412)throw std::runtime_error("Index update returned status "+std::to_string(response.status));
 }
 throw std::runtime_error("Index changed repeatedly during cleanup");
}

} // namespace reduped
