#include "reduped/algorithms.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <queue>
#include <stdexcept>
#include <vector>

namespace reduped {
namespace {

constexpr double pi = 3.14159265358979323846;

std::vector<double> resize_gray(std::span<const std::uint8_t> input,int width,int height,int out_w,int out_h,
                                double left=0,double top=0,double right=-1,double bottom=-1){
    if(width<=0||height<=0||input.size()<static_cast<std::size_t>(width)*height)throw std::runtime_error("Invalid grayscale image");
    if(right<0)right=width;if(bottom<0)bottom=height;
    std::vector<double> out(static_cast<std::size_t>(out_w)*out_h);
    const double src_w=std::max(1.0,right-left),src_h=std::max(1.0,bottom-top);
    for(int y=0;y<out_h;++y){
        const double sy=top+((y+0.5)*src_h/out_h)-0.5;const int y0=std::clamp(static_cast<int>(std::floor(sy)),0,height-1),y1=std::min(height-1,y0+1);const double fy=std::clamp(sy-y0,0.0,1.0);
        for(int x=0;x<out_w;++x){
            const double sx=left+((x+0.5)*src_w/out_w)-0.5;const int x0=std::clamp(static_cast<int>(std::floor(sx)),0,width-1),x1=std::min(width-1,x0+1);const double fx=std::clamp(sx-x0,0.0,1.0);
            const auto at=[&](int xx,int yy){return static_cast<double>(input[static_cast<std::size_t>(yy)*width+xx]);};
            const double a=at(x0,y0)*(1-fx)+at(x1,y0)*fx,b=at(x0,y1)*(1-fx)+at(x1,y1)*fx;
            out[static_cast<std::size_t>(y)*out_w+x]=a*(1-fy)+b*fy;
        }
    }
    return out;
}

template<class T> double median(std::vector<T> values){
    if(values.empty())return 0;const auto mid=values.begin()+static_cast<std::ptrdiff_t>(values.size()/2);std::nth_element(values.begin(),mid,values.end());
    if(values.size()%2)return static_cast<double>(*mid);const auto lower=std::max_element(values.begin(),mid);return (static_cast<double>(*lower)+static_cast<double>(*mid))/2.0;
}

std::vector<double> dct2(const std::vector<double>& input,int size,int keep){
    std::vector<double> tmp(static_cast<std::size_t>(keep)*size),out(static_cast<std::size_t>(keep)*keep);
    for(int u=0;u<keep;++u)for(int y=0;y<size;++y){double sum=0;for(int x=0;x<size;++x)sum+=input[static_cast<std::size_t>(y)*size+x]*std::cos(pi*(2*x+1)*u/(2.0*size));tmp[static_cast<std::size_t>(u)*size+y]=2.0*sum;}
    for(int u=0;u<keep;++u)for(int v=0;v<keep;++v){double sum=0;for(int y=0;y<size;++y)sum+=tmp[static_cast<std::size_t>(u)*size+y]*std::cos(pi*(2*y+1)*v/(2.0*size));out[static_cast<std::size_t>(v)*keep+u]=2.0*sum;}
    return out;
}

std::uint64_t dhash_region(std::span<const std::uint8_t> gray,int width,int height,double l,double t,double r,double b){
    const auto pixels=resize_gray(gray,width,height,9,8,l,t,r,b);std::uint64_t value=0;int bit=0;
    for(int y=0;y<8;++y)for(int x=0;x<8;++x,++bit)if(pixels[static_cast<std::size_t>(y)*9+x+1]>pixels[static_cast<std::size_t>(y)*9+x])value|=(std::uint64_t{1}<<(63-bit));
    return value;
}

std::vector<double> gaussian_then_median(std::vector<double> image,int size){
    constexpr std::array<double,5> kernel{1.0,4.0,6.0,4.0,1.0};std::vector<double> temp(image.size()),blur(image.size()),filtered(image.size());
    for(int y=0;y<size;++y)for(int x=0;x<size;++x){double sum=0,w=0;for(int k=-2;k<=2;++k){const int xx=std::clamp(x+k,0,size-1);sum+=image[static_cast<std::size_t>(y)*size+xx]*kernel[k+2];w+=kernel[k+2];}temp[static_cast<std::size_t>(y)*size+x]=sum/w;}
    for(int y=0;y<size;++y)for(int x=0;x<size;++x){double sum=0,w=0;for(int k=-2;k<=2;++k){const int yy=std::clamp(y+k,0,size-1);sum+=temp[static_cast<std::size_t>(yy)*size+x]*kernel[k+2];w+=kernel[k+2];}blur[static_cast<std::size_t>(y)*size+x]=sum/w;}
    for(int y=0;y<size;++y)for(int x=0;x<size;++x){std::array<double,9> values{};int n=0;for(int dy=-1;dy<=1;++dy)for(int dx=-1;dx<=1;++dx)values[n++]=blur[static_cast<std::size_t>(std::clamp(y+dy,0,size-1))*size+std::clamp(x+dx,0,size-1)];std::nth_element(values.begin(),values.begin()+4,values.end());filtered[static_cast<std::size_t>(y)*size+x]=values[4];}
    return filtered;
}

void box1d(const float* in,float* out,int length,int stride,int full_window){
    const int half=(full_window+2)/2,phase1=half-1,phase2=full_window-half+1,phase3=length-full_window,phase4=half-1;int li=0,ri=0,oi=0,current=0;float sum=0;
    for(int i=0;i<phase1;++i){sum+=in[ri];++current;ri+=stride;}
    for(int i=0;i<phase2;++i){sum+=in[ri];++current;out[oi]=sum/current;ri+=stride;oi+=stride;}
    for(int i=0;i<phase3;++i){sum+=in[ri];sum-=in[li];out[oi]=sum/current;li+=stride;ri+=stride;oi+=stride;}
    for(int i=0;i<phase4;++i){sum-=in[li];--current;out[oi]=sum/current;li+=stride;oi+=stride;}
}

void jarosz(std::vector<float>& a,std::vector<float>& b,int rows,int cols,int window_x,int window_y){
    for(int rep=0;rep<2;++rep){for(int y=0;y<rows;++y)box1d(&a[static_cast<std::size_t>(y)*cols],&b[static_cast<std::size_t>(y)*cols],cols,1,window_x);for(int x=0;x<cols;++x)box1d(&b[x],&a[x],rows,cols,window_y);}
}

Hash256 pdq_bits(const std::array<std::array<float,16>,16>& coeff){
    std::vector<float> flat;flat.reserve(256);for(const auto& row:coeff)flat.insert(flat.end(),row.begin(),row.end());const double med=median(flat);Hash256 hash{};
    for(int i=0;i<256;++i)if(flat[static_cast<std::size_t>(i)]>med)hash[static_cast<std::size_t>(i)/64]|=(std::uint64_t{1}<<(63-(i%64)));
    return hash;
}

} // namespace

std::uint64_t imagehash_phash(std::span<const std::uint8_t> gray,int width,int height){
    const auto pixels=resize_gray(gray,width,height,32,32);const auto low=dct2(pixels,32,8);const double med=median(low);std::uint64_t hash=0;
    for(int i=0;i<64;++i)if(low[static_cast<std::size_t>(i)]>med)hash|=(std::uint64_t{1}<<(63-i));return hash;
}

std::vector<std::uint64_t> imagehash_crop_resistant(std::span<const std::uint8_t> gray,int width,int height){
    constexpr int size=300;auto segmented=gaussian_then_median(resize_gray(gray,width,height,size,size),size);std::vector<unsigned char> seen(static_cast<std::size_t>(size)*size);std::vector<std::array<int,4>> boxes;
    auto collect=[&](bool bright){
        for(int sy=0;sy<size;++sy)for(int sx=0;sx<size;++sx){const auto start=static_cast<std::size_t>(sy)*size+sx;if(seen[start]||((segmented[start]>128.0)!=bright))continue;std::queue<std::pair<int,int>> q;q.push({sx,sy});seen[start]=1;int count=0,minx=sx,maxx=sx,miny=sy,maxy=sy;
            while(!q.empty()){auto [x,y]=q.front();q.pop();++count;minx=std::min(minx,x);maxx=std::max(maxx,x);miny=std::min(miny,y);maxy=std::max(maxy,y);constexpr int dx[4]={-1,1,0,0},dy[4]={0,0,-1,1};for(int k=0;k<4;++k){const int nx=x+dx[k],ny=y+dy[k];if(nx<0||ny<0||nx>=size||ny>=size)continue;const auto p=static_cast<std::size_t>(ny)*size+nx;if(seen[p]||((segmented[p]>128.0)!=bright))continue;seen[p]=1;q.push({nx,ny});}}
            if(count>500)boxes.push_back({minx,miny,maxx,maxy});
        }
    };
    collect(true);collect(false);if(boxes.empty())boxes.push_back({0,0,size-1,size-1});std::vector<std::uint64_t> hashes;hashes.reserve(boxes.size());
    for(const auto& box:boxes){const double l=static_cast<double>(box[0])*width/size,t=static_cast<double>(box[1])*height/size,r=static_cast<double>(box[2]+1)*width/size,b=static_cast<double>(box[3]+1)*height/size;hashes.push_back(dhash_region(gray,width,height,l,t,r,b));}
    return hashes;
}

std::pair<Hash256,int> meta_pdq(std::span<const std::uint8_t> gray,int width,int height){
    if(width<5||height<5)return {Hash256{},0};const std::size_t n=static_cast<std::size_t>(width)*height;std::vector<float> a(n),b(n);for(std::size_t i=0;i<n;++i)a[i]=gray[i];
    const int wx=(width+127)/128,wy=(height+127)/128;jarosz(a,b,height,width,std::max(1,wx),std::max(1,wy));
    std::array<std::array<float,64>,64> small{};for(int y=0;y<64;++y){const int sy=std::min(height-1,static_cast<int>(((y+0.5)*height)/64));for(int x=0;x<64;++x){const int sx=std::min(width-1,static_cast<int>(((x+0.5)*width)/64));small[y][x]=a[static_cast<std::size_t>(sy)*width+sx];}}
    int gradient=0;for(int y=0;y<63;++y)for(int x=0;x<64;++x)gradient+=std::abs(static_cast<int>(((small[y][x]-small[y+1][x])*100)/255));for(int y=0;y<64;++y)for(int x=0;x<63;++x)gradient+=std::abs(static_cast<int>(((small[y][x]-small[y][x+1])*100)/255));const int quality=std::min(100,gradient/90);
    std::array<std::array<float,16>,64> temp{};std::array<std::array<float,16>,16> coeff{};const float scale=std::sqrt(2.0f/64.0f);
    for(int y=0;y<64;++y)for(int u=0;u<16;++u){float sum=0;for(int x=0;x<64;++x)sum+=small[y][x]*scale*static_cast<float>(std::cos((pi/128.0)*(u+1)*(2*x+1)));temp[y][u]=sum;}
    for(int v=0;v<16;++v)for(int u=0;u<16;++u){float sum=0;for(int y=0;y<64;++y)sum+=temp[y][u]*scale*static_cast<float>(std::cos((pi/128.0)*(v+1)*(2*y+1)));coeff[v][u]=sum;}
    return {pdq_bits(coeff),quality};
}

NativeStillHashes compute_native_still_hashes(std::span<const std::uint8_t> gray,int width,int height){
    NativeStillHashes out;out.phash=imagehash_phash(gray,width,height);auto [pdq,quality]=meta_pdq(gray,width,height);out.pdq=pdq;out.pdq_quality=quality;out.crop_hashes=imagehash_crop_resistant(gray,width,height);return out;
}

} // namespace reduped
