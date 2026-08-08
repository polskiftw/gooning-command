#include "reduped/evidence_windows.hpp"

#include "reduped/algorithms.hpp"
#include "reduped/fingerprint.hpp"

#include <windows.h>
#include <wincodec.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <propvarutil.h>
#include <shlwapi.h>
#include <wrl/client.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace reduped {
namespace {

void check(HRESULT result,std::string_view message){if(FAILED(result))throw std::runtime_error(std::string(message)+" (HRESULT "+std::to_string(static_cast<unsigned>(result))+")");}

std::vector<std::uint8_t> gray_from_bgra(const std::uint8_t* pixels,int width,int height,int stride){
    std::vector<std::uint8_t> gray(static_cast<std::size_t>(width)*height);
    for(int y=0;y<height;++y)for(int x=0;x<width;++x){const auto* p=pixels+static_cast<std::ptrdiff_t>(y)*stride+x*4;gray[static_cast<std::size_t>(y)*width+x]=static_cast<std::uint8_t>((29*p[0]+150*p[1]+77*p[2])>>8);}
    return gray;
}

struct NormalizedGray { std::vector<std::uint8_t> pixels; int width{}; int height{}; };

NormalizedGray normalize_gray(std::span<const std::uint8_t> source,int width,int height){
    constexpr int max_dimension=1024;
    if(width<=max_dimension&&height<=max_dimension)return {std::vector<std::uint8_t>(source.begin(),source.end()),width,height};
    const double scale=static_cast<double>(max_dimension)/std::max(width,height);const int out_w=std::max(1,static_cast<int>(std::round(width*scale))),out_h=std::max(1,static_cast<int>(std::round(height*scale)));
    std::vector<std::uint8_t> out(static_cast<std::size_t>(out_w)*out_h);
    for(int y=0;y<out_h;++y){const double sy=((y+0.5)*height/out_h)-0.5;const int y0=std::clamp(static_cast<int>(std::floor(sy)),0,height-1),y1=std::min(height-1,y0+1);const double fy=std::clamp(sy-y0,0.0,1.0);
        for(int x=0;x<out_w;++x){const double sx=((x+0.5)*width/out_w)-0.5;const int x0=std::clamp(static_cast<int>(std::floor(sx)),0,width-1),x1=std::min(width-1,x0+1);const double fx=std::clamp(sx-x0,0.0,1.0);const auto at=[&](int xx,int yy){return source[static_cast<std::size_t>(yy)*width+xx];};const double a=at(x0,y0)*(1-fx)+at(x1,y0)*fx,b=at(x0,y1)*(1-fx)+at(x1,y1)*fx;out[static_cast<std::size_t>(y)*out_w+x]=static_cast<std::uint8_t>(std::clamp(std::lround(a*(1-fy)+b*fy),0L,255L));}}
    return {std::move(out),out_w,out_h};
}

struct FrameEvidence{std::uint64_t phash{};Hash256 pdq{};int quality{};std::vector<std::uint64_t> crop;};
struct BufferUnlock{IMFMediaBuffer* buffer{};~BufferUnlock(){if(buffer)buffer->Unlock();}};

FrameEvidence frame_evidence(std::span<const std::uint8_t> gray,int width,int height){
    auto normalized=normalize_gray(gray,width,height);auto hashes=compute_native_still_hashes(normalized.pixels,normalized.width,normalized.height);return {hashes.phash,hashes.pdq,hashes.pdq_quality,std::move(hashes.crop_hashes)};
}

std::filesystem::path temporary_file(std::span<const std::uint8_t> bytes,std::string_view key){wchar_t directory[MAX_PATH];if(!GetTempPathW(MAX_PATH,directory))throw std::runtime_error("Unable to find temporary directory");const auto extension=std::filesystem::path(std::string(key)).extension().wstring();std::filesystem::path path=std::filesystem::path(directory)/(L"reduped-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(GetTickCount64())+extension);std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));if(!out)throw std::runtime_error("Unable to prepare video for native decoding");return path;}

} // namespace

struct WindowsEvidenceGenerator::Impl{
    ComPtr<IWICImagingFactory> wic;
    Impl(){check(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&wic)),"Unable to initialize image decoder");check(MFStartup(MF_VERSION,MFSTARTUP_LITE),"Unable to initialize video decoder");}
    ~Impl(){MFShutdown();}

    std::vector<std::uint8_t> decode_wic_frame(IWICBitmapFrameDecode* frame,int& width,int& height){UINT w{},h{};check(frame->GetSize(&w,&h),"Unable to read image dimensions");width=static_cast<int>(w);height=static_cast<int>(h);ComPtr<IWICFormatConverter> converter;check(wic->CreateFormatConverter(&converter),"Unable to create image converter");check(converter->Initialize(frame,GUID_WICPixelFormat32bppBGRA,WICBitmapDitherTypeNone,nullptr,0,WICBitmapPaletteTypeCustom),"Unable to convert image pixels");std::vector<std::uint8_t> pixels(static_cast<std::size_t>(w)*h*4);check(converter->CopyPixels(nullptr,w*4,static_cast<UINT>(pixels.size()),pixels.data()),"Unable to decode image pixels");return gray_from_bgra(pixels.data(),width,height,static_cast<int>(w*4));}

    Evidence image(const ObjectRecord& object,std::span<const std::uint8_t> bytes,int max_frames,std::atomic_bool& cancelled){Evidence out;out.key=object.key;out.sha256=sha256_hex(bytes);ComPtr<IWICStream> stream;check(wic->CreateStream(&stream),"Unable to create image stream");check(stream->InitializeFromMemory(const_cast<BYTE*>(bytes.data()),static_cast<DWORD>(bytes.size())),"Unable to read image bytes");ComPtr<IWICBitmapDecoder> decoder;check(wic->CreateDecoderFromStream(stream.Get(),nullptr,WICDecodeMetadataCacheOnDemand,&decoder),"Unsupported or damaged image");UINT count{};check(decoder->GetFrameCount(&count),"Unable to count image frames");if(!count)throw std::runtime_error("Image contains no frames");const UINT step=std::max<UINT>(1,(count+static_cast<UINT>(max_frames)-1)/static_cast<UINT>(max_frames));int best=-1;double duration_ms=0;
        for(UINT i=0;i<count&&!cancelled.load();i+=step){ComPtr<IWICBitmapFrameDecode> frame;check(decoder->GetFrame(i,&frame),"Unable to decode image frame");int width{},height{};auto gray=decode_wic_frame(frame.Get(),width,height);auto evidence=frame_evidence(gray,width,height);if(count>1){out.video_hashes.push_back(evidence.pdq);out.video_qualities.push_back(evidence.quality);}if(evidence.quality>best){best=evidence.quality;out.width=width;out.height=height;out.phash=evidence.phash;out.pdq=evidence.pdq;out.pdq_quality=evidence.quality;out.crop_hashes=std::move(evidence.crop);}}
        if(count>1)out.duration_seconds=duration_ms/1000.0;return out;}

    Evidence video(const ObjectRecord& object,std::span<const std::uint8_t> bytes,double configured_interval,int max_frames,std::atomic_bool& cancelled){Evidence out;out.key=object.key;out.sha256=sha256_hex(bytes);const auto path=temporary_file(bytes,object.key);struct Remove{std::filesystem::path path;~Remove(){std::error_code ignored;std::filesystem::remove(path,ignored);}}remove{path};
        ComPtr<IMFSourceReader> reader;check(MFCreateSourceReaderFromURL(path.c_str(),nullptr,&reader),"Unsupported or damaged video");ComPtr<IMFMediaType> output;check(MFCreateMediaType(&output),"Unable to configure video decoder");check(output->SetGUID(MF_MT_MAJOR_TYPE,MFMediaType_Video),"Unable to configure video decoder");check(output->SetGUID(MF_MT_SUBTYPE,MFVideoFormat_RGB32),"Unable to configure video pixels");check(reader->SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM,nullptr,output.Get()),"Unable to decode video pixels");ComPtr<IMFMediaType> actual;check(reader->GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM,&actual),"Unable to inspect video");UINT32 width{},height{};check(MFGetAttributeSize(actual.Get(),MF_MT_FRAME_SIZE,&width,&height),"Unable to read video dimensions");out.width=static_cast<int>(width);out.height=static_cast<int>(height);
        PROPVARIANT duration;PropVariantInit(&duration);double duration_seconds=0;if(SUCCEEDED(reader->GetPresentationAttribute(MF_SOURCE_READER_MEDIASOURCE,MF_PD_DURATION,&duration))&&duration.vt==VT_UI8)duration_seconds=duration.uhVal.QuadPart/10000000.0;PropVariantClear(&duration);out.duration_seconds=duration_seconds;
        double interval=configured_interval;if(duration_seconds>0&&duration_seconds<=10.0)interval=std::max(1.0/30.0,duration_seconds/static_cast<double>(max_frames));else if(duration_seconds>0)interval=std::max(interval,duration_seconds/static_cast<double>(max_frames));
        int best=-1;for(int index=0;index<max_frames&&!cancelled.load();++index){PROPVARIANT position;PropVariantInit(&position);position.vt=VT_I8;position.hVal.QuadPart=static_cast<LONGLONG>(index*interval*10000000.0);if(FAILED(reader->SetCurrentPosition(GUID_NULL,position))){PropVariantClear(&position);break;}PropVariantClear(&position);DWORD stream{},flags{};LONGLONG timestamp{};ComPtr<IMFSample> sample;check(reader->ReadSample(MF_SOURCE_READER_FIRST_VIDEO_STREAM,0,&stream,&flags,&timestamp,&sample),"Video frame decoding failed");if(flags&MF_SOURCE_READERF_ENDOFSTREAM||!sample)break;ComPtr<IMFMediaBuffer> buffer;check(sample->ConvertToContiguousBuffer(&buffer),"Unable to read video frame");BYTE* pixels{};DWORD length{};check(buffer->Lock(&pixels,nullptr,&length),"Unable to access video frame");BufferUnlock unlock{buffer.Get()};const int stride=static_cast<int>(width*4);if(length<width*height*4)throw std::runtime_error("Decoded video frame is truncated");auto gray=gray_from_bgra(pixels,static_cast<int>(width),static_cast<int>(height),stride);auto evidence=frame_evidence(gray,static_cast<int>(width),static_cast<int>(height));out.video_hashes.push_back(evidence.pdq);out.video_qualities.push_back(evidence.quality);if(evidence.quality>best){best=evidence.quality;out.phash=evidence.phash;out.pdq=evidence.pdq;out.pdq_quality=evidence.quality;out.crop_hashes=std::move(evidence.crop);}if(duration_seconds>0&&(index+1)*interval>=duration_seconds)break;}
        if(out.video_hashes.empty())throw std::runtime_error("No decodable video frames were found");return out;}
};

WindowsEvidenceGenerator::WindowsEvidenceGenerator():impl_(std::make_unique<Impl>()){}
WindowsEvidenceGenerator::~WindowsEvidenceGenerator()=default;
Evidence WindowsEvidenceGenerator::generate(const ObjectRecord& object,std::span<const std::uint8_t> bytes,double interval,int max_frames,std::atomic_bool& cancelled){if(bytes.empty())throw std::runtime_error("Downloaded object is empty");if(object.media_kind==MediaKind::video)return impl_->video(object,bytes,interval,max_frames,cancelled);return impl_->image(object,bytes,max_frames,cancelled);}

} // namespace reduped
