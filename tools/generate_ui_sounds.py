"""Generate original noda feedback tones (stdlib only, no external recordings)."""
import math
from pathlib import Path
import struct
import wave

RATE = 24000
PATTERNS = {
    'mic_on': [(660,.09),(880,.12)], 'mic_off': [(660,.09),(440,.12)],
    'sound_on': [(520,.09),(780,.14)], 'sound_off': [(780,.09),(390,.14)],
    'voice_join': [(440,.08),(660,.08),(880,.16)],
    'voice_leave': [(660,.08),(440,.08),(330,.16)],
    'call_start': [(523,.09),(659,.09),(784,.2)],
    'call_end': [(659,.1),(523,.1),(392,.22)],
    'outgoing': [(440,.45),(0,.2),(440,.45),(0,2.2)],
    'incoming': [(659,.18),(784,.18),(988,.22),(0,.16),(784,.18),(988,.22),(0,1.8)],
}

def generate(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name, notes in PATTERNS.items():
        samples=[]
        for frequency,duration in notes:
            count=round(RATE*duration)
            for i in range(count):
                t=i/RATE
                envelope=min(1,t/.012,(duration-t)/.035)
                tone=math.sin(2*math.pi*frequency*t)+.12*math.sin(4*math.pi*frequency*t)
                samples.append(round(10000*max(0,envelope)*tone) if frequency else 0)
            if frequency:samples.extend([0]*240)
        with wave.open(str(destination/f'{name}.wav'),'wb') as out:
            out.setparams((1,2,RATE,0,'NONE','not compressed'))
            out.writeframes(struct.pack('<'+'h'*len(samples),*samples))

if __name__=='__main__':
    generate(Path(__file__).resolve().parents[1]/'client/assets/sounds')
