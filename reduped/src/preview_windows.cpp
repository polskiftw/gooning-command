#include "reduped/preview_windows.hpp"

#include <windows.h>
#include <wincodec.h>
#include <shobjidl.h>
#include <wrl/client.h>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <stdexcept>

using Microsoft::WRL::ComPtr;

namespace reduped {
namespace {

void check(HRESULT result,std::string_view message){if(FAILED(result))throw std::runtime_error(std::string(message));}

HBITMAP bitmap_from_source(IWICImagingFactory* factory,IWICBitmapSource* source,int target_width,int target_height){
 UINT width{},height{};check(source->GetSize(&width,&height),"Unable to read preview size");const double scale=std::min(static_cast<double>(target_width)/width,static_cast<double>(target_height)/height);const UINT out_width=std::max<UINT>(1,static_cast<UINT>(width*scale)),out_height=std::max<UINT>(1,static_cast<UINT>(height*scale));
 ComPtr<IWICBitmapScaler> scaler;check(factory->CreateBitmapScaler(&scaler),"Unable to create preview scaler");check(scaler->Initialize(source,out_width,out_height,WICBitmapInterpolationModeFant),"Unable to scale preview");ComPtr<IWICFormatConverter> converter;check(factory->CreateFormatConverter(&converter),"Unable to create preview converter");check(converter->Initialize(scaler.Get(),GUID_WICPixelFormat32bppPBGRA,WICBitmapDitherTypeNone,nullptr,0,WICBitmapPaletteTypeCustom),"Unable to convert preview");
 BITMAPINFO info{};info.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);info.bmiHeader.biWidth=static_cast<LONG>(out_width);info.bmiHeader.biHeight=-static_cast<LONG>(out_height);info.bmiHeader.biPlanes=1;info.bmiHeader.biBitCount=32;info.bmiHeader.biCompression=BI_RGB;void* pixels{};HDC dc=GetDC(nullptr);HBITMAP bitmap=CreateDIBSection(dc,&info,DIB_RGB_COLORS,&pixels,nullptr,0);ReleaseDC(nullptr,dc);if(!bitmap)throw std::runtime_error("Unable to allocate preview bitmap");
 if(FAILED(converter->CopyPixels(nullptr,out_width*4,out_width*out_height*4,static_cast<BYTE*>(pixels)))){DeleteObject(bitmap);throw std::runtime_error("Unable to decode preview pixels");}return bitmap;
}

std::filesystem::path temp_file(std::span<const std::uint8_t> bytes,std::string_view key){wchar_t directory[MAX_PATH];GetTempPathW(MAX_PATH,directory);const auto extension=std::filesystem::path(std::string(key)).extension().wstring();auto path=std::filesystem::path(directory)/(L"reduped-preview-"+std::to_wstring(GetCurrentThreadId())+L"-"+std::to_wstring(GetTickCount64())+extension);std::ofstream output(path,std::ios::binary);output.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));if(!output)throw std::runtime_error("Unable to prepare video preview");return path;}

} // namespace

PreviewFrames::~PreviewFrames(){for(auto bitmap:frames)if(bitmap)DeleteObject(bitmap);}
PreviewFrames::PreviewFrames(PreviewFrames&& other)noexcept:frames(std::move(other.frames)),delays_ms(std::move(other.delays_ms)){other.frames.clear();}
PreviewFrames& PreviewFrames::operator=(PreviewFrames&& other)noexcept{if(this!=&other){for(auto bitmap:frames)if(bitmap)DeleteObject(bitmap);frames=std::move(other.frames);delays_ms=std::move(other.delays_ms);other.frames.clear();}return *this;}

PreviewFrames prepare_preview(std::span<const std::uint8_t> bytes,std::string_view key,MediaKind kind,int width,int height){
 PreviewFrames result;if(kind==MediaKind::video){const auto path=temp_file(bytes,key);struct Remove{std::filesystem::path p;~Remove(){std::error_code e;std::filesystem::remove(p,e);}}remove{path};ComPtr<IShellItem> item;check(SHCreateItemFromParsingName(path.c_str(),nullptr,IID_PPV_ARGS(&item)),"Unable to open video preview");ComPtr<IShellItemImageFactory> images;check(item.As(&images),"Video thumbnail service is unavailable");HBITMAP bitmap{};check(images->GetImage({width,height},SIIGBF_BIGGERSIZEOK|SIIGBF_RESIZETOFIT,&bitmap),"Unable to decode video thumbnail");result.frames.push_back(bitmap);result.delays_ms.push_back(1000);return result;}
 ComPtr<IWICImagingFactory> factory;check(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&factory)),"Unable to initialize preview decoder");ComPtr<IWICStream> stream;check(factory->CreateStream(&stream),"Unable to create preview stream");check(stream->InitializeFromMemory(const_cast<BYTE*>(bytes.data()),static_cast<DWORD>(bytes.size())),"Unable to read preview bytes");ComPtr<IWICBitmapDecoder> decoder;check(factory->CreateDecoderFromStream(stream.Get(),nullptr,WICDecodeMetadataCacheOnDemand,&decoder),"Unable to decode preview");UINT count{};decoder->GetFrameCount(&count);const UINT limit=40,step=std::max<UINT>(1,(count+limit-1)/limit);for(UINT i=0;i<count;i+=step){ComPtr<IWICBitmapFrameDecode> frame;check(decoder->GetFrame(i,&frame),"Unable to decode preview frame");result.frames.push_back(bitmap_from_source(factory.Get(),frame.Get(),width,height));result.delays_ms.push_back(count>1?100:1000);}return result;
}

} // namespace reduped
