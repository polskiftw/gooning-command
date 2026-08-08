#include "reduped/app_win32.hpp"

#include <windows.h>
#include <commctrl.h>
#include <objbase.h>

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,LPWSTR,int show_command){
    INITCOMMONCONTROLSEX controls{sizeof(controls),ICC_BAR_CLASSES|ICC_STANDARD_CLASSES};
    InitCommonControlsEx(&controls);
    const auto initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    const int result=reduped::run_windows_app(instance,show_command);
    if(SUCCEEDED(initialized))CoUninitialize();
    return result;
}
