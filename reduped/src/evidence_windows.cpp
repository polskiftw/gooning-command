#include "reduped/evidence_windows.hpp"

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
#include <array>
#include <atomic>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <numeric>
#include <stdexcept>

using Microsoft::WRL::ComPtr;

namespace reduped {
namespace {

void check(HRESULT result,std::string_view message){if(FAILED(result))throw std::runtime_error(std::string(message)+" (HRESULT "+std::to_string(static_cast<unsigned>(result))+")");}

std::vector<std::uint8_t> gray_from_bgra(const std::uint8_t* pixels,int width,int height,int stride,int target=96){
 std::vector<std::uint8_t> gray(static_cast<std::size_t>(target*target));
 for(int y=0;y<target;++y)for(int x=0;x<target;++x){const int sx=std::clamp(x*width/target,0,width-1),sy=std::clamp(y*height/target,0,height-1);const auto* p=pixels+static_cast<std::ptrdiff_t>(sy)*stride+sx*4;gray[static_cast<std::size_t>(y*target+x)]=static_cast<std::uint8_t>((29*p[0]+150*p[1]+77*p[2])>>8);}
 return gray;
}

std::vector<double> resize_gray(std::span<const std::uint8_t> source,int source_size,int target,int offset_x=0,int offset_y=0,int region_size=-1){
 if(region_size<0)region_size=source_size;std::vector<double> out(static_cast<std::size_t>(target*target));
 for(int y=0;y<target;++y)for(int x=0;x<target;++x){const int sx=std::clamp(offset_x+x*region_size/target,0,source_size-1),sy=std::clamp(offset_y+y*region_size/target,0,source_size-1);out[static_cast<std::size_t>(y*target+x)]=source[static_cast<std::size_t>(sy*source_size+sx)];}return out;
}

std::vector<double> dct2(const std::vector<double>& input,int size,int frequencies){
 constexpr double pi=3.14159265358979323846;std::vector<double> out(static_cast<std::size_t>(frequencies*frequencies));
 std::vector<double> cosines(static_cast<std::size_t>(frequencies*size));for(int u=0;u<frequencies;++u)for(int x=0;x<size;++x)cosines[static_cast<std::size_t>(u*size+x)]=std::cos(pi*(2*x+1)*u/(2.0*size));
 for(int v=0;v<frequencies;++v)for(int u=0;u<frequencies;++u){double sum=0;for(int y=0;y<size;++y)for(int x=0;x<size;++x)sum+=input[static_cast<std::size_t>(y*size+x)]*cosines[static_cast<std::size_t>(u*size+x)]*cosines[static_cast<std::size_t>(v*size+y)];out[static_cast<std::size_t>(v*frequencies+u)]=sum;}return out;
}

std::uint64_t phash(std::span<const std::uint8_t> gray,int source_size,int ox=0,int oy=0,int region=-1){auto resized=resize_gray(gray,source_size,32,ox,oy,region);auto coefficients=dct2(resized,32,8);std::vector<double> values(coefficients.begin()+1,coefficients.end());const auto middle=values.begin()+static_cast<std::ptrdiff_t>(values.size()/2);std::nth_element(values.begin(),middle,values.end());const double median=*middle;std::uint64_t hash=0;for(std::size_t i=0;i<coefficients.size();++i)if(coefficients[i]>median)hash|=(std::uint64_t{1}<<i);return hash;}

Hash256 pdq(std::span<const std::uint8_t> gray,int source_size){auto resized=resize_gray(gray,source_size,64);auto coefficients=dct2(resized,64,16);std::vector<double> values(coefficients.begin()+1,coefficients.end());const auto middle=values.begin()+static_cast<std::ptrdiff_t>(values.size()/2);std::nth_element(values.begin(),middle,values.end());const double median=*middle;Hash256 hash{};for(std::size_t i=0;i<256;++i)if(coefficients[i]>median)hash[i/64]|=(std::uint64_t{1}<<(i%64));return hash;}

int quality(std::span<const std::uint8_t> gray,int size){std::uint64_t total=0;for(int y=1;y<size;++y)for(int x=1;x<size;++x){const auto here=gray[static_cast<std::size_t>(y*size+x)];total+=std::abs(static_cast<int>(here)-gray[static_cast<std::size_t>(y*size+x-1)]);total+=std::abs(static_cast<int>(here)-gray[static_cast<std::size_t>((y-1)*size+x)]);}const auto normalized=total/static_cast<std::uint64_t>(2*(size-1)*(size-1));return std::clamp(static_cast<int>(normalized*4),0,100);}

struct FrameEvidence{std::uint64_t phash{};Hash256 pdq{};int quality{};std::vector<std::uint64_t> crop;};
struct BufferUnlock{IMFMediaBuffer* buffer{};~BufferUnlock(){if(buffer)buffer->Unlock();}};
FrameEvidence frame_evidence(std::span<const std::uint8_t> gray,int size){FrameEvidence out{phash(gray,size),pdq(gray,size),quality(gray,size),{}};const int tile=size*2/3;for(int row=0;row<2;++row)for(int col=0;col<2;++col)out.crop.push_back(phash(gray,size,col*(size-tile),row*(size-tile),tile));out.crop.push_back(phash(gray,size,size/6,size/6,size*2/3));return out;}

std::filesystem::path temporary_file(std::span<const std::uint8_t> bytes,std::string_view key){wchar_t directory[MAX_PATH];if(!GetTempPathW(MAX_PATH,directory))throw std::runtime_error("Unable to find temporary directory");const auto extension=std::filesystem::path(std::string(key)).extension().wstring();std::filesystem::path path=std::filesystem::path(directory)/(L"reduped-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(GetTickCount64())+extension);std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));if(!out)throw std::runtime_error("Unable to prepare video for native decoding");return path;}

} // namespace

struct WindowsEvidenceGenerator::Impl{
 ComPtr<IWICImagingFactory> wic;
 Impl(){check(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&wic)),"Unable to initialize image decoder");check(MFStartup(MF_VERSION,MFSTARTUP_LITE),"Unable to initialize video decoder");}
 ~Impl(){MFShutdown();}

 std::vector<std::uint8_t> decode_wic_frame(IWICBitmapFrameDecode* frame,int& width,int& height){UINT w{},h{};check(frame->GetSize(&w,&h),"Unable to read image dimensions");width=static_cast<int>(w);height=static_cast<int>(h);ComPtr<IWICFormatConverter> converter;check(wic->CreateFormatConverter(&converter),"Unable to create image converter");check(converter->Initialize(frame,GUID_WICPixelFormat32bppBGRA,WICBitmapDitherTypeNone,nullptr,0,WICBitmapPaletteTypeCustom),"Unable to convert image pixels");std::vector<std::uint8_t> pixels(static_cast<std::size_t>(w*h*4));check(converter->CopyPixels(nullptr,w*4,static_cast<UINT>(pixels.size()),pixels.data()),"Unable to decode image pixels");return gray_from_bgra(pixels.data(),static_cast<int>(w),static_cast<int>(h),static_cast<int>(w*4));}

 Evidence image(const ObjectRecord& object,std::span<const std::uint8_t> bytes,int max_frames,std::atomic_bool& cancelled){Evidence out;out.key=object.key;out.sha256=sha256_hex(bytes);ComPtr<IWICStream> stream;check(wic->CreateStream(&stream),"Unable to create image stream");check(stream->InitializeFromMemory(const_cast<BYTE*>(bytes.data()),static_cast<DWORD>(bytes.size())),"Unable to read image bytes");ComPtr<IWICBitmapDecoder> decoder;check(wic->CreateDecoderFromStream(stream.Get(),nullptr,WICDecodeMetadataCacheOnDemand,&decoder),"Unsupported or damaged image");UINT count{};check(decoder->GetFrameCount(&count),"Unable to count image frames");if(!count)throw std::runtime_error("Image contains no frames");const UINT step=std::max<UINT>(1,(count+static_cast<UINT>(max_frames)-1)/static_cast<UINT>(max_frames));int best=-1;for(UINT i=0;i<count&&!cancelled.load();i+=step){ComPtr<IWICBitmapFrameDecode> frame;check(decoder->GetFrame(i,&frame),"Unable to decode image frame");int width{},height{};auto gray=decode_wic_frame(frame.Get(),width,height);auto evidence=frame_evidence(gray,96);out.video_hashes.push_back(evidence.pdq);if(evidence.quality>best){best=evidence.quality;out.width=width;out.height=height;out.phash=evidence.phash;out.pdq=evidence.pdq;out.pdq_quality=evidence.quality;out.crop_hashes=std::move(evidence.crop);}}
 if(count<=1)out.video_hashes.clear();return out;}

 Evidence video(const ObjectRecord& object,std::span<const std::uint8_t> bytes,double configured_interval,int max_frames,std::atomic_bool& cancelled){Evidence out;out.key=object.key;out.sha256=sha256_hex(bytes);const auto path=temporary_file(bytes,object.key);struct Remove{std::filesystem::path path;~Remove(){std::error_code ignored;std::filesystem::remove(path,ignored);}}remove{path};
  ComPtr<IMFSourceReader> reader;check(MFCreateSourceReaderFromURL(path.c_str(),nullptr,&reader),"Unsupported or damaged video");ComPtr<IMFMediaType> output;check(MFCreateMediaType(&output),"Unable to configure video decoder");check(output->SetGUID(MF_MT_MAJOR_TYPE,MFMediaType_Video),"Unable to configure video decoder");check(output->SetGUID(MF_MT_SUBTYPE,MFVideoFormat_RGB32),"Unable to configure video pixels");check(reader->SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM,nullptr,output.Get()),"Unable to decode video pixels");ComPtr<IMFMediaType> actual;check(reader->GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM,&actual),"Unable to inspect video");UINT32 width{},height{};check(MFGetAttributeSize(actual.Get(),MF_MT_FRAME_SIZE,&width,&height),"Unable to read video dimensions");out.width=static_cast<int>(width);out.height=static_cast<int>(height);
  PROPVARIANT duration;PropVariantInit(&duration);double duration_seconds=0;
  if(SUCCEEDED(reader->GetPresentationAttribute(MF_SOURCE_READER_MEDIASOURCE,MF_PD_DURATION,&duration))&&duration.vt==VT_UI8)duration_seconds=duration.uhVal.QuadPart/10000000.0;PropVariantClear(&duration);out.duration_seconds=duration_seconds;
  double interval=configured_interval;if(duration_seconds>0&&duration_seconds<=10.0)interval=std::max(1.0/30.0,duration_seconds/static_cast<double>(max_frames));else if(duration_seconds>0)interval=std::max(interval,duration_seconds/static_cast<double>(max_frames));
  int best=-1;for(int index=0;index<max_frames&&!cancelled.load();++index){PROPVARIANT position;PropVariantInit(&position);position.vt=VT_I8;position.hVal.QuadPart=static_cast<LONGLONG>(index*interval*10000000.0);if(FAILED(reader->SetCurrentPosition(GUID_NULL,position))){PropVariantClear(&position);break;}PropVariantClear(&position);DWORD stream{},flags{};LONGLONG timestamp{};ComPtr<IMFSample> sample;check(reader->ReadSample(MF_SOURCE_READER_FIRST_VIDEO_STREAM,0,&stream,&flags,&timestamp,&sample),"Video frame decoding failed");if(flags&MF_SOURCE_READERF_ENDOFSTREAM||!sample)break;ComPtr<IMFMediaBuffer> buffer;check(sample->ConvertToContiguousBuffer(&buffer),"Unable to read video frame");BYTE* pixels{};DWORD length{};check(buffer->Lock(&pixels,nullptr,&length),"Unable to access video frame");BufferUnlock unlock{buffer.Get()};const int stride=static_cast<int>(width*4);if(length<width*height*4)throw std::runtime_error("Decoded video frame is truncated");auto gray=gray_from_bgra(pixels,static_cast<int>(width),static_cast<int>(height),stride);auto evidence=frame_evidence(gray,96);out.video_hashes.push_back(evidence.pdq);if(evidence.quality>best){best=evidence.quality;out.phash=evidence.phash;out.pdq=evidence.pdq;out.pdq_quality=evidence.quality;out.crop_hashes=std::move(evidence.crop);}if(duration_seconds>0&&(index+1)*interval>=duration_seconds)break;}
  if(out.video_hashes.empty())throw std::runtime_error("No decodable video frames were found");return out;}
};

WindowsEvidenceGenerator::WindowsEvidenceGenerator():impl_(std::make_unique<Impl>()){}
WindowsEvidenceGenerator::~WindowsEvidenceGenerator()=default;
Evidence WindowsEvidenceGenerator::generate(const ObjectRecord& object,std::span<const std::uint8_t> bytes,double interval,int max_frames,std::atomic_bool& cancelled){if(bytes.empty())throw std::runtime_error("Downloaded object is empty");if(object.media_kind==MediaKind::video)return impl_->video(object,bytes,interval,max_frames,cancelled);return impl_->image(object,bytes,max_frames,cancelled);}

} // namespace reduped
