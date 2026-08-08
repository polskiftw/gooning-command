#include "reduped/app_win32.hpp"

#include "reduped/config.hpp"
#include "reduped/database.hpp"
#include "reduped/deletion.hpp"
#include "reduped/evidence_windows.hpp"
#include "reduped/pipeline.hpp"
#include "reduped/preview_windows.hpp"
#include "reduped/r2_winhttp.hpp"

#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlwapi.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <condition_variable>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>

namespace reduped {
namespace {

constexpr UINT message_status=WM_APP+1,message_pipeline_done=WM_APP+2,message_preview=WM_APP+3,message_action_done=WM_APP+4;
enum ControlId{previous_id=100,next_id,exclude_id,nuke_id,nuke_sha_id,left_link_id,right_link_id,left_delete_id,right_delete_id,slider_id};

std::wstring wide(std::string_view text){if(text.empty())return {};const int size=MultiByteToWideChar(CP_UTF8,0,text.data(),static_cast<int>(text.size()),nullptr,0);std::wstring out(static_cast<std::size_t>(size),L'\0');MultiByteToWideChar(CP_UTF8,0,text.data(),static_cast<int>(text.size()),out.data(),size);return out;}
std::string narrow(std::wstring_view text){if(text.empty())return {};const int size=WideCharToMultiByte(CP_UTF8,0,text.data(),static_cast<int>(text.size()),nullptr,0,nullptr,nullptr);std::string out(static_cast<std::size_t>(size),'\0');WideCharToMultiByte(CP_UTF8,0,text.data(),static_cast<int>(text.size()),out.data(),size,nullptr,nullptr);return out;}

std::filesystem::path executable_directory(){std::wstring path(32768,L'\0');const auto length=GetModuleFileNameW(nullptr,path.data(),static_cast<DWORD>(path.size()));path.resize(length);return std::filesystem::path(path).parent_path();}

struct PreviewJob{int side{};std::uint64_t revision{};std::string key;MediaKind kind{MediaKind::unknown};};
struct PreviewResult{int side{};std::uint64_t revision{};std::string key;PreviewFrames preview;std::string error;};
struct ActionResult{bool success{};std::string error;};

class App{
public:
 App(HINSTANCE instance,int show):instance_(instance),show_(show){
  const auto directory=executable_directory();config_=Config::load(directory/L"config.txt");std::filesystem::create_directories(directory/L"data");database_=std::make_unique<Database>(directory/L"data"/L"deduper.sqlite3");store_=std::make_unique<WinHttpObjectStore>(config_);
 }
 ~App(){shutdown_workers();}
 int run(){
  WNDCLASSW type{};type.lpfnWndProc=&App::window_proc;type.hInstance=instance_;type.lpszClassName=L"RedupedMainWindow";type.hCursor=LoadCursor(nullptr,IDC_ARROW);type.hbrBackground=CreateSolidBrush(RGB(24,24,28));RegisterClassW(&type);
  window_=CreateWindowExW(0,type.lpszClassName,L"Reduped",WS_OVERLAPPEDWINDOW,CW_USEDEFAULT,CW_USEDEFAULT,1400,900,nullptr,nullptr,instance_,this);if(!window_)throw std::runtime_error("Unable to create the application window");
  create_controls();reload_generation();start_preview_workers();ShowWindow(window_,show_);UpdateWindow(window_);start_pipeline();
  MSG message{};while(GetMessageW(&message,nullptr,0,0)>0){TranslateMessage(&message);DispatchMessageW(&message);}return static_cast<int>(message.wParam);
 }
private:
 static LRESULT CALLBACK window_proc(HWND window,UINT message,WPARAM wp,LPARAM lp){
  App* self=reinterpret_cast<App*>(GetWindowLongPtrW(window,GWLP_USERDATA));
  try{
   if(message==WM_NCCREATE){self=static_cast<App*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);self->window_=window;SetWindowLongPtrW(window,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(self));}
   return self?self->handle(message,wp,lp):DefWindowProcW(window,message,wp,lp);
  }catch(const std::exception& e){return self?self->callback_failure(message,e.what()):DefWindowProcW(window,message,wp,lp);}
   catch(...){return self?self->callback_failure(message,"Unexpected internal UI failure"):DefWindowProcW(window,message,wp,lp);}
 }

 LRESULT callback_failure(UINT message,std::string_view error)noexcept{
  validated_=false;validation_failed_=true;busy_.store(false);cancelled_.store(true);
  for(HWND item:{previous_,next_,exclude_,nuke_,nuke_sha_,left_link_,right_link_,left_delete_,right_delete_,slider_})if(item)EnableWindow(item,FALSE);
  if(status_){
   try{const auto text=wide(std::string("Reduped entered a safe error state: ")+std::string(error));SetWindowTextW(status_,text.c_str());}
   catch(...){SetWindowTextW(status_,L"Reduped entered a safe error state.");}
  }
  if(message==WM_CLOSE){try{shutdown_workers();}catch(...){}if(window_)DestroyWindow(window_);}
  return 0;
 }

 HWND control(const wchar_t* cls,const wchar_t* text,DWORD style,int id){return CreateWindowExW(0,cls,text,WS_CHILD|WS_VISIBLE|style,0,0,10,10,window_,reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),instance_,nullptr);}
 void create_controls(){
  previous_=control(WC_BUTTONW,L"Previous",BS_PUSHBUTTON,previous_id);next_=control(WC_BUTTONW,L"Next",BS_PUSHBUTTON,next_id);exclude_=control(WC_BUTTONW,L"Exclude",BS_PUSHBUTTON,exclude_id);nuke_=control(WC_BUTTONW,L"NUKE",BS_PUSHBUTTON,nuke_id);nuke_sha_=control(WC_BUTTONW,L"NUKE SHA ONLY",BS_PUSHBUTTON,nuke_sha_id);
  slider_=control(TRACKBAR_CLASSW,L"",TBS_HORZ|TBS_AUTOTICKS,slider_id);SendMessageW(slider_,TBM_SETRANGE,TRUE,MAKELPARAM(0,99));SendMessageW(slider_,TBM_SETPOS,TRUE,config_.slider);
  pair_label_=control(WC_STATICW,L"No certified pair",SS_CENTER,0);status_=control(WC_STATICW,L"Loading saved queue",SS_LEFT,0);
  left_preview_=control(WC_STATICW,L"",SS_BITMAP|SS_CENTERIMAGE,0);right_preview_=control(WC_STATICW,L"",SS_BITMAP|SS_CENTERIMAGE,0);
  left_link_=control(WC_BUTTONW,L"",BS_FLAT,left_link_id);right_link_=control(WC_BUTTONW,L"",BS_FLAT,right_link_id);
  left_delete_=control(WC_BUTTONW,L"BYE BITCH",BS_PUSHBUTTON,left_delete_id);right_delete_=control(WC_BUTTONW,L"BYE BITCH",BS_PUSHBUTTON,right_delete_id);
  SetTimer(window_,1,50,nullptr);layout();update_actionability();
 }

 void layout(){RECT rect{};GetClientRect(window_,&rect);const int width=rect.right,height=rect.bottom,margin=16,top=14,bar=34,gap=18;int x=margin;for(HWND item:{previous_,next_,exclude_,nuke_,nuke_sha_}){const int item_width=item==nuke_sha_?150:100;MoveWindow(item,x,top,item_width,bar,TRUE);x+=item_width+8;}MoveWindow(slider_,x+12,top,width-x-margin-12,bar,TRUE);
  const int panel_top=top+bar+42,panel_bottom=height-95,panel_width=(width-margin*2-gap)/2;MoveWindow(left_preview_,margin,panel_top,panel_width,panel_bottom-panel_top-78,TRUE);MoveWindow(right_preview_,margin+panel_width+gap,panel_top,panel_width,panel_bottom-panel_top-78,TRUE);MoveWindow(left_link_,margin,panel_bottom-72,panel_width,30,TRUE);MoveWindow(right_link_,margin+panel_width+gap,panel_bottom-72,panel_width,30,TRUE);MoveWindow(left_delete_,margin,panel_bottom-38,panel_width,36,TRUE);MoveWindow(right_delete_,margin+panel_width+gap,panel_bottom-38,panel_width,36,TRUE);MoveWindow(pair_label_,margin,top+bar+7,width-margin*2,25,TRUE);MoveWindow(status_,margin,height-72,width-margin*2,56,TRUE);
 }

 void post_status(std::string text){if(closing_.load())return;PostMessageW(window_,message_status,0,reinterpret_cast<LPARAM>(new std::wstring(wide(text))));}
 void set_status(std::string_view text){SetWindowTextW(status_,wide(text).c_str());}

 void reload_generation(){
  generation_=database_->active_generation();if(!generation_){pair_index_=0;render_pair();return;}pair_index_=std::min(generation_->review_position,generation_->pairs.empty()?std::size_t{0}:generation_->pairs.size()-1);SendMessageW(slider_,TBM_SETPOS,TRUE,generation_->identity.slider);render_pair();
 }

 std::optional<ReviewPair> current_pair()const{if(!generation_||generation_->pairs.empty()||pair_index_>=generation_->pairs.size())return std::nullopt;return generation_->pairs[pair_index_];}
 RenderedPairToken token()const{const auto pair=current_pair();if(!pair)throw std::runtime_error("No certified pair selected");return {pair->generation_id,pair->family_id,pair->id,pair->left_key,pair->right_key,pair->revision};}

 void clear_previews(){SendMessageW(left_preview_,STM_SETIMAGE,IMAGE_BITMAP,0);SendMessageW(right_preview_,STM_SETIMAGE,IMAGE_BITMAP,0);displayed_[0]=PreviewFrames{};displayed_[1]=PreviewFrames{};frame_index_={0,0};}
 void render_pair(){
  ++preview_revision_;clear_previews();const auto pair=current_pair();if(!pair){SetWindowTextW(pair_label_,generation_?L"Certified queue is empty":L"No certified queue exists yet");SetWindowTextW(left_link_,L"");SetWindowTextW(right_link_,L"");update_actionability();return;}
  SetWindowTextW(left_link_,wide(pair->left_key).c_str());SetWindowTextW(right_link_,wide(pair->right_key).c_str());const auto label=std::to_wstring(pair_index_+1)+L" / "+std::to_wstring(generation_->pairs.size())+L"    Difference "+std::to_wstring(pair->difference).substr(0,5)+(pair->excluded?L"    EXCLUDED":L"");SetWindowTextW(pair_label_,label.c_str());
  enqueue_preview({0,preview_revision_,pair->left_key,kind_for_key(pair->left_key)});enqueue_preview({1,preview_revision_,pair->right_key,kind_for_key(pair->right_key)});database_->save_review_position(generation_->id,pair_index_);update_actionability();
 }

 MediaKind kind_for_key(const std::string& key)const{auto objects=database_->live_assets();auto found=std::find_if(objects.begin(),objects.end(),[&](const auto& o){return o.key==key;});return found==objects.end()?MediaKind::unknown:found->media_kind;}

 void navigate(int delta){if(!generation_||generation_->pairs.empty())return;const auto count=static_cast<long long>(generation_->pairs.size());pair_index_=static_cast<std::size_t>((static_cast<long long>(pair_index_)+delta+count)%count);render_pair();}

 void update_actionability(){ActionabilityInput input;input.active_generation_certified=generation_.has_value();input.startup_inventory_validated=validated_;input.current_pair_exists=current_pair().has_value();input.current_pair_certified=current_pair().has_value()&&!current_pair()->excluded;input.current_family_certified=input.current_pair_certified;input.allow_delete=config_.allow_delete;input.destructive_operation_running=busy_.load();input.validation_failed=validation_failed_;auto state=compute_actionability(input);EnableWindow(previous_,generation_&&!generation_->pairs.empty());EnableWindow(next_,generation_&&!generation_->pairs.empty());EnableWindow(exclude_,state.can_review_mutate&&input.current_pair_certified);EnableWindow(left_delete_,state.can_delete_single);EnableWindow(right_delete_,state.can_delete_single);EnableWindow(nuke_,state.can_nuke&&generation_&&!database_->visual_nuke_plan(generation_->id).empty());EnableWindow(nuke_sha_,state.can_nuke_sha&&generation_&&!database_->exact_nuke_plan(generation_->id).empty());EnableWindow(slider_,!busy_.load());if(!busy_.load()&&state.reason!="Certified queue ready")set_status(state.reason);}

 void start_pipeline(){if(busy_.exchange(true))return;validated_=false;validation_failed_=false;update_actionability();cancelled_.store(false);if(startup_.joinable())startup_.join();startup_=std::thread([this]{const auto initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);StartupOutcome outcome=StartupOutcome::validation_failed;try{WindowsEvidenceGenerator generator;DeletionService deletion(*database_,*store_,config_);if(config_.allow_delete){deletion.recover_prepared([this](auto s){post_status(std::string(s));});deletion.retry_index_cleanup([this](auto s){post_status(std::string(s));});}CertificationPipeline pipeline(*database_,*store_,generator,config_);outcome=pipeline.run(cancelled_,[this](auto s){post_status(std::string(s));});if(outcome==StartupOutcome::validated_existing||outcome==StartupOutcome::certified_new)pipeline.recertify_pending(cancelled_,[this](auto s){post_status(std::string(s));});}catch(const std::exception& e){post_status(std::string("Validation failed: ")+e.what());}if(SUCCEEDED(initialized))CoUninitialize();PostMessageW(window_,message_pipeline_done,static_cast<WPARAM>(outcome),0);});}

 void start_action(std::function<void(DeletionService&,const DeletionService::Status&)> operation){if(busy_.exchange(true))return;update_actionability();if(action_.joinable())action_.join();action_=std::thread([this,operation=std::move(operation)]{const auto initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);auto* result=new ActionResult;try{DeletionService deletion(*database_,*store_,config_);operation(deletion,[this](auto s){post_status(std::string(s));});WindowsEvidenceGenerator generator;CertificationPipeline pipeline(*database_,*store_,generator,config_);pipeline.recertify_pending(cancelled_,[this](auto s){post_status(std::string(s));});result->success=true;}catch(const std::exception& e){result->error=e.what();}if(SUCCEEDED(initialized))CoUninitialize();PostMessageW(window_,message_action_done,0,reinterpret_cast<LPARAM>(result));});}

 void exclude_current(){if(!validated_)return;const auto current=token();if(database_->exclude_pair(current)){reload_generation();if(generation_&&!generation_->pairs.empty()){pair_index_=std::min(pair_index_+1,generation_->pairs.size()-1);render_pair();}}}

 void open_media(bool left){const auto pair=current_pair();if(!pair)return;if(config_.public_media_base.empty()){set_status("PUBLIC_MEDIA_BASE is not configured");return;}const auto key=left?pair->left_key:pair->right_key;std::wstring raw=wide(config_.public_media_base);if(!raw.empty()&&raw.back()!=L'/')raw+=L'/';raw+=wide(key);std::wstring escaped(raw.size()*3+16,L'\0');DWORD length=static_cast<DWORD>(escaped.size());if(SUCCEEDED(UrlEscapeW(raw.c_str(),escaped.data(),&length,URL_ESCAPE_PERCENT|URL_ESCAPE_SEGMENT_ONLY))){escaped.resize(length);ShellExecuteW(window_,L"open",escaped.c_str(),nullptr,nullptr,SW_SHOWNORMAL);}else ShellExecuteW(window_,L"open",raw.c_str(),nullptr,nullptr,SW_SHOWNORMAL);}

 void start_preview_workers(){for(auto& worker:preview_workers_)worker=std::thread([this]{const auto initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);while(true){PreviewJob job;{std::unique_lock lock(preview_mutex_);preview_condition_.wait(lock,[&]{return closing_.load()||preview_jobs_[0]||preview_jobs_[1];});if(closing_.load())break;const int side=preview_jobs_[0]?0:1;job=std::move(*preview_jobs_[side]);preview_jobs_[side].reset();}auto* result=new PreviewResult;result->side=job.side;result->revision=job.revision;result->key=job.key;try{auto bytes=store_->download(job.key,cancelled_);result->preview=prepare_preview(bytes,job.key,job.kind,620,560);}catch(const std::exception& e){result->error=e.what();}if(!closing_.load())PostMessageW(window_,message_preview,0,reinterpret_cast<LPARAM>(result));else delete result;}if(SUCCEEDED(initialized))CoUninitialize();});}
 void enqueue_preview(PreviewJob job){{std::lock_guard lock(preview_mutex_);preview_jobs_[job.side]=std::move(job);}preview_condition_.notify_one();}

 void animate(){const auto now=GetTickCount64();for(int side=0;side<2;++side){auto& preview=displayed_[side];if(preview.frames.size()<2||now<next_frame_at_[side])continue;frame_index_[side]=(frame_index_[side]+1)%preview.frames.size();SendMessageW(side==0?left_preview_:right_preview_,STM_SETIMAGE,IMAGE_BITMAP,reinterpret_cast<LPARAM>(preview.frames[frame_index_[side]]));next_frame_at_[side]=now+preview.delays_ms[frame_index_[side]];}}

 void shutdown_workers(){if(closing_.exchange(true))return;cancelled_.store(true);preview_condition_.notify_all();if(startup_.joinable())startup_.join();if(action_.joinable())action_.join();for(auto& worker:preview_workers_)if(worker.joinable())worker.join();}

 LRESULT handle(UINT message,WPARAM wp,LPARAM lp){
  switch(message){
   case WM_SIZE:layout();return 0;
   case WM_TIMER:animate();return 0;
   case WM_HSCROLL:if(reinterpret_cast<HWND>(lp)==slider_&&LOWORD(wp)==TB_ENDTRACK){const int value=static_cast<int>(SendMessageW(slider_,TBM_GETPOS,0,0));if(value!=config_.slider){config_.slider=value;start_pipeline();}}return 0;
   case WM_COMMAND:{const int id=LOWORD(wp);if(HIWORD(wp)!=BN_CLICKED)return 0;try{if(id==previous_id)navigate(-1);else if(id==next_id)navigate(1);else if(id==exclude_id)exclude_current();else if(id==left_link_id)open_media(true);else if(id==right_link_id)open_media(false);else if(id==left_delete_id){const auto current=token();start_action([current](auto& service,const auto& status){service.delete_single(current,true,status);});}else if(id==right_delete_id){const auto current=token();start_action([current](auto& service,const auto& status){service.delete_single(current,false,status);});}else if(id==nuke_id&&generation_){const auto gid=generation_->id;start_action([gid](auto& service,const auto& status){service.nuke_visual(gid,status);});}else if(id==nuke_sha_id&&generation_){const auto gid=generation_->id;start_action([gid](auto& service,const auto& status){service.nuke_exact(gid,status);});}}catch(const std::exception& e){set_status(e.what());}return 0;}
   case message_status:{std::unique_ptr<std::wstring> text(reinterpret_cast<std::wstring*>(lp));SetWindowTextW(status_,text->c_str());return 0;}
   case message_pipeline_done:{const auto outcome=static_cast<StartupOutcome>(wp);busy_.store(false);validated_=outcome==StartupOutcome::validated_existing||outcome==StartupOutcome::certified_new;validation_failed_=outcome==StartupOutcome::validation_failed;reload_generation();if(validated_)set_status("Certified queue ready");update_actionability();return 0;}
   case message_action_done:{std::unique_ptr<ActionResult> result(reinterpret_cast<ActionResult*>(lp));busy_.store(false);reload_generation();set_status(result->success?"Certified queue ready":result->error);update_actionability();return 0;}
   case message_preview:{std::unique_ptr<PreviewResult> result(reinterpret_cast<PreviewResult*>(lp));const auto pair=current_pair();const auto expected=pair?(result->side==0?pair->left_key:pair->right_key):std::string{};if(preview_result_is_current(result->revision,result->key,preview_revision_,expected)&&result->error.empty()){SendMessageW(result->side==0?left_preview_:right_preview_,STM_SETIMAGE,IMAGE_BITMAP,0);displayed_[result->side]=std::move(result->preview);frame_index_[result->side]=0;if(!displayed_[result->side].frames.empty()){SendMessageW(result->side==0?left_preview_:right_preview_,STM_SETIMAGE,IMAGE_BITMAP,reinterpret_cast<LPARAM>(displayed_[result->side].frames[0]));next_frame_at_[result->side]=GetTickCount64()+displayed_[result->side].delays_ms[0];}}else if(result->revision==preview_revision_&&!result->error.empty())set_status(std::string("Preview failed: ")+result->error);return 0;}
   case WM_CLOSE:if(generation_)database_->save_review_position(generation_->id,pair_index_);shutdown_workers();DestroyWindow(window_);return 0;
   case WM_DESTROY:PostQuitMessage(0);return 0;
  }
  return DefWindowProcW(window_,message,wp,lp);
 }

 HINSTANCE instance_{};int show_{};HWND window_{},previous_{},next_{},exclude_{},nuke_{},nuke_sha_{},slider_{},pair_label_{},status_{},left_preview_{},right_preview_{},left_link_{},right_link_{},left_delete_{},right_delete_{};
 Config config_;std::unique_ptr<Database> database_;std::unique_ptr<WinHttpObjectStore> store_;std::optional<GenerationSnapshot> generation_;std::size_t pair_index_{};bool validated_{},validation_failed_{};std::atomic_bool busy_{false},cancelled_{false},closing_{false};std::thread startup_,action_;std::uint64_t preview_revision_{};
 std::array<std::thread,2> preview_workers_;std::mutex preview_mutex_;std::condition_variable preview_condition_;std::array<std::optional<PreviewJob>,2> preview_jobs_;std::array<PreviewFrames,2> displayed_;std::array<std::size_t,2> frame_index_{};std::array<ULONGLONG,2> next_frame_at_{};
};

} // namespace

int run_windows_app(HINSTANCE instance,int show_command){try{App app(instance,show_command);return app.run();}catch(const std::exception& error){MessageBoxW(nullptr,wide(error.what()).c_str(),L"Reduped could not start",MB_OK|MB_ICONERROR);return 1;}}

} // namespace reduped
