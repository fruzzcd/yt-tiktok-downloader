import os
import re
import uuid
import threading
import time
import shutil
from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import requests

app = Flask(__name__)

PAPKA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')

if not os.path.exists(PAPKA):
    os.makedirs(PAPKA)

ffmpeg = None
mesta = [
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Links'),
    r'C:\ffmpeg\bin',
    r'C:\Program Files\ffmpeg\bin',
]
for m in mesta:
    if os.path.exists(os.path.join(m, 'ffmpeg.exe')):
        ffmpeg = m
        break

if not ffmpeg and shutil.which('ffmpeg'):
    ffmpeg = os.path.dirname(shutil.which('ffmpeg'))

print('ffmpeg:', ffmpeg)

zadachi = {}


def youtube(link):
    return 'youtube.com' in link or 'youtu.be' in link

def tiktok(link):
    return 'tiktok.com' in link

def pinterest(link):
    return 'pinterest' in link or 'pin.it' in link

def instagram(link):
    return 'instagram.com' in link or 'instagr.am' in link

def najti_link(text):
    urls = re.findall(r'https?://\S+', text)
    return urls[0] if urls else text.strip()


def skachat(link, tip='video'):
    uid = str(uuid.uuid4())[:8]
    thumb = None

    if pinterest(link):
        n = {'quiet': True, 'no_warnings': True, 'socket_timeout': 30}
        with yt_dlp.YoutubeDL(n) as ydl:
            info = ydl.extract_info(link, download=False)
            url = info.get('url') or info.get('thumbnail')
            thumb = info.get('thumbnail')
            if url:
                r = requests.get(url, timeout=30)
                ext = 'png' if 'png' in r.headers.get('content-type', '') else 'jpg'
                fayl = f'{PAPKA}/{uid}.{ext}'
                with open(fayl, 'wb') as f:
                    f.write(r.content)
                return fayl, info.get('title', 'Pinterest'), 'photo', thumb
        return None, None, None, None

    if youtube(link) and tip == 'audio':
        n = {
            'format': 'bestaudio/best',
            'outtmpl': f'{PAPKA}/{uid}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            'socket_timeout': 30,
            'retries': 3,
        }
        if ffmpeg:
            n['ffmpeg_location'] = ffmpeg
        with yt_dlp.YoutubeDL(n) as ydl:
            info = ydl.extract_info(link, download=True)
            fayl = ydl.prepare_filename(info)
            fayl = fayl.rsplit('.', 1)[0] + '.mp3'
            thumb = info.get('thumbnail')
            return fayl, info.get('title', 'audio'), 'audio', thumb

    n = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        'outtmpl': f'{PAPKA}/{uid}.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
        'socket_timeout': 30,
        'retries': 3,
    }
    if tiktok(link):
        n['impersonate'] = 'chrome'
        n['http_headers']['Referer'] = 'https://www.tiktok.com/'
    if ffmpeg:
        n['ffmpeg_location'] = ffmpeg
    else:
        n['format'] = 'best[ext=mp4]/best'

    with yt_dlp.YoutubeDL(n) as ydl:
        info = ydl.extract_info(link, download=True)
        fayl = ydl.prepare_filename(info)
        if not fayl.endswith('.mp4'):
            fayl = fayl.rsplit('.', 1)[0] + '.mp4'

        ext = info.get('ext', 'mp4')
        foto = ext in ['jpg', 'jpeg', 'png', 'webp'] or 'image' in info.get('format', '')
        thumb = info.get('thumbnail')

        return fayl, info.get('title', 'video'), 'photo' if foto else 'video', thumb


def rabotnik(task_id, link, tip):
    try:
        zadachi[task_id]['status'] = 'loading'
        fayl, title, media, thumb = skachat(link, tip)
        if fayl and os.path.exists(fayl):
            zadachi[task_id]['status'] = 'done'
            zadachi[task_id]['file'] = fayl
            zadachi[task_id]['title'] = title
            zadachi[task_id]['type'] = media
            zadachi[task_id]['thumb'] = thumb
            zadachi[task_id]['size'] = round(os.path.getsize(fayl) / 1024 / 1024, 1)
        else:
            zadachi[task_id]['status'] = 'error'
            zadachi[task_id]['error'] = 'не получилось скачать'
    except Exception as e:
        zadachi[task_id]['status'] = 'error'
        zadachi[task_id]['error'] = str(e)[:200]


def chistka():
    while True:
        time.sleep(300)
        now = time.time()
        for tid in list(zadachi.keys()):
            if now - zadachi[tid].get('time', now) > 600:
                fayl = zadachi[tid].get('file')
                if fayl and os.path.exists(fayl):
                    os.remove(fayl)
                del zadachi[tid]

threading.Thread(target=chistka, daemon=True).start()


@app.route('/')
def glavnaya():
    return render_template('index.html')


@app.route('/download', methods=['POST'])
def zagruzka():
    data = request.json
    link = najti_link(data.get('link', ''))
    tip = data.get('type', 'video')

    if not link:
        return jsonify({'error': 'вставь ссылку'}), 400

    if not (youtube(link) or tiktok(link) or pinterest(link) or instagram(link)):
        return jsonify({'error': 'поддерживаю только youtube, tiktok, pinterest, instagram'}), 400

    task_id = str(uuid.uuid4())[:8]
    zadachi[task_id] = {'status': 'loading', 'time': time.time()}

    t = threading.Thread(target=rabotnik, args=(task_id, link, tip))
    t.start()

    return jsonify({'task_id': task_id, 'youtube': youtube(link)})


@app.route('/status/<task_id>')
def statuss(task_id):
    z = zadachi.get(task_id)
    if not z:
        return jsonify({'error': 'не найдено'}), 404
    return jsonify(z)


@app.route('/file/<task_id>')
def otdat_fayl(task_id):
    z = zadachi.get(task_id)
    if not z or z['status'] != 'done':
        return jsonify({'error': 'файл не готов'}), 404

    fayl = z['file']
    title = z.get('title', 'download')
    title = re.sub(r'[^\w\s-]', '', title)[:50]
    ext = fayl.rsplit('.', 1)[-1]

    return send_file(os.path.abspath(fayl), as_attachment=True, download_name=f'{title}.{ext}')


if __name__ == '__main__':
    print('http://localhost:5000')
    app.run(debug=False, port=5000)
