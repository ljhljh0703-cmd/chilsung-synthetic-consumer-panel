"""Dependency-free scientific line chart for the deterministic demonstration.
No raster asset is edited: pixels and compact bitmap labels are plotted from data.
"""
import struct
import zlib

FONT = {
'0':['111','101','101','101','111'],'1':['010','110','010','010','111'],
'2':['111','001','111','100','111'],'3':['111','001','111','001','111'],
'4':['101','101','111','001','001'],'5':['111','100','111','001','111'],
'6':['111','100','111','101','111'],'7':['111','001','010','010','010'],
'8':['111','101','111','101','111'],'9':['111','101','111','001','111'],
'A':['010','101','111','101','101'],'B':['110','101','110','101','110'],
'C':['111','100','100','100','111'],'D':['110','101','101','101','110'],
'E':['111','100','110','100','111'],'F':['111','100','110','100','100'],
'G':['111','100','101','101','111'],'H':['101','101','111','101','101'],
'I':['111','010','010','010','111'],'J':['001','001','001','101','111'],
'K':['101','101','110','101','101'],'L':['100','100','100','100','111'],
'M':['101','111','111','101','101'],'N':['101','111','111','111','101'],
'O':['111','101','101','101','111'],'P':['111','101','111','100','100'],
'Q':['111','101','101','111','001'],'R':['110','101','110','101','101'],
'S':['111','100','111','001','111'],'T':['111','010','010','010','010'],
'U':['101','101','101','101','111'],'V':['101','101','101','101','010'],
'W':['101','101','111','111','101'],'X':['101','101','010','101','101'],
'Y':['101','101','010','010','010'],'Z':['111','001','010','100','111'],
'-':['000','000','111','000','000'],'/':['001','001','010','100','100'],
':':['000','010','000','010','000'],'.':['000','000','000','000','010'],
' ':['000']*5, '(':['010','100','100','100','010'], ')':['010','001','001','001','010']}


def chart(path, rows, n, series_labels=None, title=None):
    w,h=1200,680
    data=bytearray([248,250,252])*(w*h)
    def pixel(x,y,c):
        if 0 <= x < w and 0 <= y < h:
            k=(y*w+x)*3; data[k:k+3]=bytes(c)
    def line(x1,y1,x2,y2,c,thick=1):
        steps=max(abs(x2-x1),abs(y2-y1),1)
        for i in range(steps+1):
            x=round(x1+(x2-x1)*i/steps); y=round(y1+(y2-y1)*i/steps)
            for dx in range(thick):
                for dy in range(thick): pixel(x+dx,y+dy,c)
    def text(s,x,y,scale=3,c=(44,55,66)):
        for ch in s.upper():
            for yy,row in enumerate(FONT.get(ch,FONT[' '])):
                for xx,bit in enumerate(row):
                    if bit=='1':
                        for dx in range(scale):
                            for dy in range(scale):pixel(x+xx*scale+dx,y+yy*scale+dy,c)
            x+=4*scale
    text(title or 'UNVALIDATED DEMONSTRATION',74,30,4)
    text('AGENTS '+str(n)+' / COUNTS - NOT MARKET FORECAST',74,65,2)
    x0,y0,x1,y1=90,130,1130,540
    maxval=max(n,max(r['cumulative_repeat'] for r in rows),max(r['cumulative_posts'] for r in rows))
    ymax=((maxval+499)//500)*500
    for i in range(5):
        yy=round(y1-(y1-y0)*i/4)
        line(x0,yy,x1,yy,(220,226,233))
        text(str(round(ymax*i/4)),12,yy-5,2)
    line(x0,y0,x0,y1,(140,153,166),2)
    line(x0,y1,x1,y1,(140,153,166),2)
    last=max(r['week'] for r in rows) or 1
    for r in rows:
        xx=round(x0+(x1-x0)*r['week']/last)
        text(str(r['week']),xx-3,y1+15,2)
    colors=[(15,118,110),(194,102,24),(75,102,180)]
    keys=['cumulative_buyers','cumulative_repeat','cumulative_posts']
    for k,c in zip(keys,colors):
        points=[(round(x0+(x1-x0)*r['week']/last),round(y1-(y1-y0)*r[k]/ymax)) for r in rows]
        for a,b in zip(points,points[1:]):line(*a,*b,c,3)
    for i,(label,c) in enumerate(zip(series_labels or ['CUMULATIVE BUYERS','REPEAT EVENTS','POSTS'],colors)):
        xx=90+i*355; line(xx,602,xx+27,602,c,4);text(label,xx+37,598,2,c)
    text('WEEK',555,570,2)
    def chunk(name,payload):
        return struct.pack('!I',len(payload))+name+payload+struct.pack('!I',zlib.crc32(name+payload)&0xffffffff)
    scan=b''.join(b'\0'+data[y*w*3:(y+1)*w*3] for y in range(h))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan,6))+chunk(b'IEND',b''))
