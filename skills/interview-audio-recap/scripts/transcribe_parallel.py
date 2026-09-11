# -*- coding: utf-8 -*-
"""分段并行转写：切 4 段 + 多进程并行 + 贪心解码提速"""
import sys, os, time, wave, io
import numpy as np
import av
from multiprocessing import Pool

AUDIO = r'C:/Users/l32524/xwechat_files/wxid_h5eyiq1tpx9k22_69f2/temp/RWTemp/2026-09/9e20f478899dc29eb19741386f9343c8/2026年09月11日 10点37分.m4a'
OUT = r'C:/Users/l32524/WorkBuddy/2026-09-01-15-32-05/.workbuddy/面试录音转写_20260911.txt'
MODEL_SIZE = 'small'
N_SEG = 4
THREADS_PER = 3
TMPDIR = r'C:/Users/l32524/AppData/Local/Temp/whisper_segs'


def decode(path):
    """解码为 16kHz 单声道 int16"""
    c = av.open(path)
    st = next(s for s in c.streams if s.type == 'audio')
    rs = av.AudioResampler(format='s16', layout='mono', rate=16000)
    chunks = []
    for fr in c.decode(st):
        for rf in rs.resample(fr):
            chunks.append(rf.to_ndarray())
    c.close()
    return np.concatenate(chunks, axis=1).flatten().astype(np.int16)


def write_wav(path, arr):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(arr.tobytes())


def work(args):
    idx, wav = args
    from faster_whisper import WhisperModel
    m = WhisperModel(MODEL_SIZE, device='cpu', compute_type='int8', cpu_threads=THREADS_PER)
    segs, info = m.transcribe(wav, language='zh', beam_size=1, vad_filter=True,
                              vad_parameters=dict(min_silence_duration_ms=500),
                              initial_prompt='这是一场技术岗位面试对话，包含中文和少量英文技术术语。')
    out = []
    for s in segs:
        out.append((s.start, s.end, s.text.strip()))
    return idx, out


if __name__ == '__main__':
    os.makedirs(TMPDIR, exist_ok=True)
    print('[1/3] 解码音频...', flush=True)
    t0 = time.time()
    data = decode(AUDIO)
    total = len(data)
    print('      样本 %d，时长 %.1f 分钟，解码耗时 %.1fs' % (total, total/16000/60, time.time()-t0), flush=True)

    bounds = [int(total * i / N_SEG) for i in range(N_SEG + 1)]
    jobs = []
    for i in range(N_SEG):
        wp = os.path.join(TMPDIR, 'seg_%d.wav' % i)
        write_wav(wp, data[bounds[i]:bounds[i+1]])
        jobs.append((i, wp))
    print('[2/3] %d 段并行转写（每段 %d 线程）...' % (N_SEG, THREADS_PER), flush=True)

    t1 = time.time()
    with Pool(N_SEG) as pool:
        results = pool.map(work, jobs)
    print('      转写耗时 %.1f 分钟' % ((time.time()-t1)/60), flush=True)

    lines = []
    for idx, segs in sorted(results):
        offset = bounds[idx] / 16000.0
        for st, en, tx in segs:
            ts = st + offset
            lines.append('[%02d:%02d] %s' % (int(ts//60), int(ts%60), tx))

    with io.open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('[3/3] 完成！%d 段文本，总耗时 %.1f 分钟' % (len(lines), (time.time()-t0)/60), flush=True)
    print('      输出: ' + OUT, flush=True)
