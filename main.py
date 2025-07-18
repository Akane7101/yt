import os
import requests
import socket
import dns.resolver
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import yt_dlp
from yt_dlp import YoutubeDL
from urllib.parse import urlparse, parse_qs
from pydantic import BaseModel
import assemblyai as aai
import uvicorn
import tempfile
import imageio
import argparse
import uuid
import subprocess
import shutil
import time

app = FastAPI()

STATIC_DIR = os.path.join(os.getcwd(), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "")

def test_dns_resolution():
    """Test DNS resolution for YouTube and suggest fixes"""
    try:
        socket.gethostbyname("www.youtube.com")
        return True, "DNS resolution working"
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"

def try_alternative_dns():
    """Try using alternative DNS servers"""
    try:

        resolver = dns.resolver.Resolver()
        resolver.nameservers = ['8.8.8.8', '8.8.4.4']
        answer = resolver.resolve('www.youtube.com', 'A')
        return True, f"Alternative DNS works: {answer[0]}"
    except Exception as e:
        return False, f"Alternative DNS failed: {e}"

def create_cookie_file():
    """Create a temporary cookie file from environment variable"""
    if not YOUTUBE_COOKIES:
        return None
    
    try:
        cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        cookie_file.write(YOUTUBE_COOKIES)
        cookie_file.flush()
        cookie_file.close()
        return cookie_file.name
    except Exception as e:
        print(f"Warning: Failed to create cookie file: {e}")
        return None

def get_ydl_opts():
    """Get YoutubeDL options with enhanced network settings"""

    dns_works, dns_msg = test_dns_resolution()
    if not dns_works:
        print(f"DNS Issue: {dns_msg}")
        alt_dns_works, alt_dns_msg = try_alternative_dns()
        print(f"Alternative DNS: {alt_dns_msg}")
    
    base_opts = {
        'quiet': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'socket_timeout': 30,
        'retries': 5,
        'fragment_retries': 5,
        'extractor_retries': 3,
        'file_access_retries': 3,
        'sleep_interval': 1,
        'max_sleep_interval': 5,

        'force_ipv4': True,  
        'source_address': '0.0.0.0', 
    }
    

    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    if proxy:
        base_opts['proxy'] = proxy
    
    cookie_file = create_cookie_file()
    if cookie_file:
        base_opts['cookiefile'] = cookie_file
    
    return base_opts

def cleanup_cookie_file(ydl_opts):
    """Clean up temporary cookie file if it was created"""
    if 'cookiefile' in ydl_opts:
        try:
            os.unlink(ydl_opts['cookiefile'])
        except Exception:
            pass

def search_video_by_title(title: str):
    """Enhanced search with better error handling and fallback options"""

    dns_works, dns_msg = test_dns_resolution()
    if not dns_works:
        raise HTTPException(
            status_code=503, 
            detail=f"DNS resolution failed for YouTube: {dns_msg}. Please check your network connection or DNS settings."
        )
    
    ydl_opts = {
        **get_ydl_opts(),
        'extract_flat': True,
        'playlist_items': '1', 
        'no_warnings': True,
    }


    search_queries = [
        f"ytsearch1:{title}", 
        f"ytsearch5:{title}",  
    ]
    
    for search_query in search_queries:
        try:
            with YoutubeDL(ydl_opts) as ydl:
                print(f"Searching with query: {search_query}")
                search_results = ydl.extract_info(search_query, download=False)
                
                if search_results and 'entries' in search_results and search_results['entries']:
                    first_entry = search_results['entries'][0]
                    if first_entry and 'url' in first_entry:
                        result = first_entry['url']
                        cleanup_cookie_file(ydl_opts)
                        return result
                        
        except Exception as e:
            print(f"Search attempt failed with {search_query}: {e}")
            continue
    
    cleanup_cookie_file(ydl_opts)
    raise HTTPException(
        status_code=404, 
        detail=f"No videos found for '{title}'. This might be due to network issues or the video not existing."
    )


@app.get("/health")
async def health_check():
    """Health check endpoint that tests DNS resolution"""
    dns_works, dns_msg = test_dns_resolution()
    alt_dns_works, alt_dns_msg = try_alternative_dns()
    
    return JSONResponse(content={
        "status": "healthy" if dns_works else "unhealthy",
        "dns_resolution": dns_msg,
        "alternative_dns": alt_dns_msg,
        "timestamp": time.time()
    })


@app.get("/test-youtube-access")
async def test_youtube_access():
    """Test endpoint to check YouTube accessibility"""
    try:

        dns_works, dns_msg = test_dns_resolution()
        

        try:
            response = requests.get("https://www.youtube.com", timeout=10)
            http_works = response.status_code == 200
            http_msg = f"HTTP connection successful: {response.status_code}"
        except Exception as e:
            http_works = False
            http_msg = f"HTTP connection failed: {e}"
        

        try:
            ydl_opts = get_ydl_opts()
            with YoutubeDL(ydl_opts) as ydl:

                test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                info = ydl.extract_info(test_url, download=False)
                ytdlp_works = info is not None
                ytdlp_msg = "yt-dlp working correctly"
        except Exception as e:
            ytdlp_works = False
            ytdlp_msg = f"yt-dlp failed: {e}"
        
        return JSONResponse(content={
            "dns_resolution": {"works": dns_works, "message": dns_msg},
            "http_connection": {"works": http_works, "message": http_msg},
            "ytdlp_functionality": {"works": ytdlp_works, "message": ytdlp_msg},
            "recommendations": get_troubleshooting_recommendations(dns_works, http_works, ytdlp_works)
        })
        
    except Exception as e:
        return JSONResponse(content={
            "error": str(e),
            "status": "failed"
        })

def get_troubleshooting_recommendations(dns_works, http_works, ytdlp_works):
    """Get troubleshooting recommendations based on test results"""
    recommendations = []
    
    if not dns_works:
        recommendations.extend([
            "Check your internet connection",
            "Try using Google DNS (8.8.8.8, 8.8.4.4) or Cloudflare DNS (1.1.1.1)",
            "Flush your DNS cache",
            "Check if you're behind a firewall or proxy that blocks YouTube"
        ])
    
    if not http_works:
        recommendations.extend([
            "Check if YouTube is accessible from your location",
            "Try using a VPN if YouTube is blocked",
            "Check proxy settings if you're in a corporate environment"
        ])
    
    if not ytdlp_works:
        recommendations.extend([
            "Update yt-dlp to the latest version",
            "Check if your IP is rate-limited by YouTube",
            "Try using cookies if you have a YouTube account"
        ])
    
    return recommendations


def extract_video_info(url: str):
    """Extract video info with enhanced error handling"""

    dns_works, dns_msg = test_dns_resolution()
    if not dns_works:
        raise HTTPException(status_code=503, detail=f"DNS resolution failed: {dns_msg}")
    
    ydl_opts = {
        **get_ydl_opts(),
        'extract_flat': False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown Title')
            formats = info.get('formats', [])
            
 
            thumbnails = info.get('thumbnails', [])
            best_thumbnail = None
            max_width = 0
            
            for thumb in thumbnails:
                width = thumb.get('width', 0)
                if width > max_width:
                    max_width = width
                    best_thumbnail = thumb.get('url')
            
            default_thumbnail = info.get('thumbnail', None)
            
            audio_video_formats = [
                {
                    'format_id': fmt['format_id'],
                    'resolution': fmt.get('resolution', 'N/A'),
                    'filesize': fmt.get('filesize') or fmt.get('filesize_approx'),
                    'url': fmt['url']
                }
                for fmt in formats if fmt.get('acodec') != 'none' and fmt.get('vcodec') != 'none'
            ]

            highest_audio = max(
                (fmt for fmt in formats if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none' and fmt.get('ext') == 'm4a'),
                key=lambda x: x.get('abr', 0),
                default=None
            )

            highest_audio_info = {
                'format_id': highest_audio['format_id'],
                'bitrate': highest_audio.get('abr', 'Unknown'),
                'filesize': highest_audio.get('filesize') or highest_audio.get('filesize_approx'),
                'url': highest_audio['url']
            } if highest_audio else None

            result = {
                "title": title,
                "formats": audio_video_formats,
                "highest_audio": highest_audio_info,
                "thumbnail": best_thumbnail or default_thumbnail
            }
            
            cleanup_cookie_file(ydl_opts)
            return result
            
        except Exception as e:
            cleanup_cookie_file(ydl_opts)
            raise HTTPException(status_code=500, detail=f"Error extracting video info: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
