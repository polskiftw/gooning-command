#include "reduped/app_win32.hpp"
#include "reduped/session.hpp"

#include <windows.h>
#include <commctrl.h>
#include <objbase.h>

#include <filesystem>
#include <stdexcept>
#include <string>

namespace {

std::filesystem::path executable_directory() {
    std::wstring path(32768, L'\0');
    const auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) throw std::runtime_error("Unable to locate Reduped executable");
    path.resize(length);
    return std::filesystem::path(path).parent_path();
}

} // namespace

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,LPWSTR,int show_command){
    INITCOMMONCONTROLSEX controls{sizeof(controls),ICC_BAR_CLASSES|ICC_STANDARD_CLASSES};
    InitCommonControlsEx(&controls);
    const auto initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    try {
        reduped::reset_session_exclusions(executable_directory()/L"data"/L"deduper.sqlite3");
    } catch (const std::exception& error) {
        MessageBoxA(nullptr,error.what(),"Reduped could not start",MB_OK|MB_ICONERROR);
        if(SUCCEEDED(initialized))CoUninitialize();
        return 1;
    }
    const int result=reduped::run_windows_app(instance,show_command);
    if(SUCCEEDED(initialized))CoUninitialize();
    return result;
}
