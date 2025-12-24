import discogs_client
import json
import time
import yt_dlp


def hyperlink(text, url):
    ESC = "\033"
    return f"{ESC}]8;;{url}{ESC}\\{text}{ESC}]8;;{ESC}\\"


def get_audio_url(video_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        return info['url']


def main():
    token = json.loads(open("discogs-auth.json", "r").read())["token"]
    discogs = discogs_client.Client('MyDiscogsApp/1.0', user_token=token)

    user = discogs.identity()
    print("logged in as:", user)

    folders = user.collection_folders
    for folder in folders:
        for item in folder.releases:
            release = item.release
            print(f"{release.title}")
            if hasattr(release, "videos"):
                unique_videos = list()
                unique_video_keys = set()
                for video in release.videos:
                    if video.url not in unique_video_keys:
                        unique_videos.append({
                            "url": video.url,
                            "title": video.title
                        })
                        unique_video_keys.add(video.url)
                for video in unique_videos:
                    audio_url = get_audio_url(video['url'])
                    link = hyperlink(video['title'], audio_url)
                    print(f"    {link}")
            time.sleep(1)

if __name__ == "__main__":
    main()
