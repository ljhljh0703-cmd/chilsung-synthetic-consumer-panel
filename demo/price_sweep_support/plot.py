"""Plot computed price scenarios directly to PNG with standard-library pixels."""
import struct,zlib
from font import FONT


def plot(path,rows,base_price,base_volume):
    w,h=1200,680;data=bytearray([248,250,252])*(w*h)
    def px(x,y,c):
        if 0<=x<w and 0<=y<h:
            k=(y*w+x)*3;data[k:k+3]=bytes(c)
    def line(x1,y1,x2,y2,c,thick=1):
        n=max(abs(x2-x1),abs(y2-y1),1)
        for i in range(n+1):
            x=round(x1+(x2-x1)*i/n);y=round(y1+(y2-y1)*i/n)
            for dx in range(thick):
                for dy in range(thick):px(x+dx,y+dy,c)
    def text(s,x,y,scale=3,c=(40,53,65)):
        for ch in s.upper():
            for yy,row in enumerate(FONT.get(ch,FONT[' '])):
                for xx,b in enumerate(row):
                    if b=='1':
                        for dx in range(scale):
                            for dy in range(scale):px(x+xx*scale+dx,y+yy*scale+dy,c)
            x+=4*scale
    text('UNVALIDATED PRICE SCENARIO',75,30,4)
    text('CHOICE SHARE - ALL RESPONSES INCLUDING NONE',75,66,2)
    lo=min(r['price'] for r in rows);hi=max(r['price'] for r in rows)
    if lo==hi:lo-=1;hi+=1
    left,top,right,bottom=100,130,1120,530
    xy=lambda r:(round(left+(r['price']-lo)/(hi-lo)*(right-left)),round(bottom-r['choice_share_all']*(bottom-top)))
    for pct in range(0,101,25):
        y=round(bottom-pct/100*(bottom-top));line(left,y,right,y,(220,226,233));text(str(pct),35,y-5,2)
    line(left,top,left,bottom,(130,145,160),2);line(left,bottom,right,bottom,(130,145,160),2)
    xbase=round(left+(base_price-lo)/(hi-lo)*(right-left))
    for y in range(top,bottom,9):line(xbase,y,xbase,min(y+3,bottom),(160,170,180))
    for price in sorted({r['price'] for r in rows}):
        x=round(left+(price-lo)/(hi-lo)*(right-left));text(str(price),x-16,bottom+17,2)
    text('PRICE - KRW',520,578,2)
    colors=[(15,118,110),(195,105,25),(79,101,184),(163,68,123),(65,121,87),(120,100,60)]
    volumes=sorted({r['effective_volume'] or 0 for r in rows})
    for idx,volume in enumerate(volumes):
        series=sorted([r for r in rows if (r['effective_volume'] or 0)==volume],key=lambda r:r['price']);points=[xy(r) for r in series];c=colors[idx%len(colors)]
        for a,b in zip(points,points[1:]):line(*a,*b,c,3)
        for x,y in points:
            for dx in range(-4,5):
                for dy in range(-4,5):px(x+dx,y+dy,c)
        x=80+(idx%4)*280;y=620+(idx//4)*22;line(x,y,x+25,y,c,3);text((str(volume)+' ML') if volume else 'ORIGINAL VOLUME',x+35,y-4,2,c)
    text('CONTROL '+str(base_price)+' KRW',820,578,2)
    def chunk(name,b):return struct.pack('!I',len(b))+name+b+struct.pack('!I',zlib.crc32(name+b)&0xffffffff)
    scan=b''.join(b'\0'+data[y*w*3:(y+1)*w*3] for y in range(h))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b''))
