#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPGManager Morocco Cloud - SNRT + Arryadia + 2M + Chada + Medi1.
Runs on GitHub Actions. The Vu+ only downloads morocco.xml.gz.
"""
from __future__ import annotations
import argparse,gzip,hashlib,html,json,re,time,unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass
from datetime import datetime,timedelta,time as dtime,timezone
from pathlib import Path
from xml.etree import ElementTree as ET
import requests
from bs4 import BeautifulSoup
from lxml import html as LH
from zoneinfo import ZoneInfo
try: import cloudscraper
except Exception: cloudscraper=None

TZ=ZoneInfo("Africa/Casablanca"); PARIS=ZoneInfo("Europe/Paris")
# Morocco returned permanently to legal GMT on 2026-09-20 at 02:00 local.
# Keep this explicit cutoff because GitHub runners and Enigma2 images may carry
# older tzdata that still reports the former permanent UTC+1 regime.
MOROCCO_GMT_EFFECTIVE_LOCAL=datetime(2026,9,20,2,0,0)

def morocco_localize(naive):
    if naive >= MOROCCO_GMT_EFFECTIVE_LOCAL:
        return naive.replace(tzinfo=timezone.utc)
    return naive.replace(tzinfo=TZ)

def morocco_wall_clock(day, tm):
    return morocco_localize(datetime.combine(day,tm))
UA="Mozilla/5.0 EPGManagerCloud/8.2.2-rc23"
CHANNELS={
 "AlAoula":"Al Aoula","Arrabiaa":"Attaqafia / Arrabiaa","AlMaghribiya":"Al Maghribia",
 "Assadisa":"Assadissa","Tamazight":"Tamazight","AFLAM.ma":"Aflam TV",
 "Arryadia_HD":"Arryadia HD","Arryadia_TNT":"Arryadia TNT","Arryadia_HD1":"Arryadia HD1",
 "Arryadia_HD2":"Arryadia HD2","Arryadia_HD3":"Arryadia HD3","2M":"2M","Chada TV":"Chada TV",
 "MEDI1TV_AR.ma":"Medi1 TV Arabic","MEDI1TV_MAGHREB.ma":"Medi1 TV Maghreb"}
GROUPS={"snrt":{"AlAoula","Arrabiaa","AlMaghribiya","Assadisa","Tamazight","AFLAM.ma"},
 "arryadia":{"Arryadia_HD","Arryadia_TNT","Arryadia_HD1","Arryadia_HD2","Arryadia_HD3"},
 "2m":{"2M"},"chada":{"Chada TV"},"medi1":{"MEDI1TV_AR.ma","MEDI1TV_MAGHREB.ma"}}
SNRT={"AlAoula":"https://www.snrt.ma/ar/node/1208","Arrabiaa":"https://www.snrt.ma/ar/node/4071",
 "AlMaghribiya":"https://www.snrt.ma/ar/node/4072","Assadisa":"https://www.snrt.ma/ar/node/4073",
 "Tamazight":"https://www.snrt.ma/ar/node/4075"}
SNRT_AR_NAMES={
 "AlAoula":"قناة الأولى","Arrabiaa":"قناة الثقافية","AlMaghribiya":"قناة المغربية",
 "Assadisa":"قناة السادسة","Tamazight":"قناة الأمازيغية","AFLAM.ma":"قناة السابعة أفلام"
}
MEDI1=(
 ("MEDI1TV_AR.ma",("https://www.medi1tv.com/ar/grille/arabic","https://www.medi1tv.ma/ar/grille/arabic")),
 ("MEDI1TV_MAGHREB.ma",("https://www.medi1tv.ma/ar/grille/maghreb","https://www.medi1tv.com/ar/grille/maghreb")))
ARR_IDS=["Arryadia_HD","Arryadia_TNT","Arryadia_HD1","Arryadia_HD2","Arryadia_HD3"]
ARR_TAGS={r"\btnt\b":"Arryadia_TNT",r"\bsat\b":"Arryadia_HD",r"\bhd1\b":"Arryadia_HD1",r"\bhd2\b":"Arryadia_HD2",r"\bhd3\b":"Arryadia_HD3"}
NEWS={"الظهيرة":"أخبار الظهيرة","الأمازيغية":"الأخبار الأمازيغية","الفرنسية":"الأخبار الفرنسية",
 "الإسبانية":"الأخبار الإسبانية","الرئيسية":"الأخبار الرئيسية","الأخيرة":"الأخبار الأخيرة","الرياضية":"أخبار الرياضة"}
T2M={
 "addam al machrouk":"الدم المشروك",
 "al akhbar":"الأخبار","sabahiyat 2m":"صباحيات 2M","sabahiyat":"صباحيات 2M",
 "ahsane patissier":"أحسن حلواني","andaloussiyat":"أندلسيات","lharba":"الهربة",
 "sahatna jmi3":"صحتنا جميع","tajwid al qor an":"تجويد القرآن","ch hiwat bladi":"شهيوات بلادي",
 "kif al hal":"كيف الحال","al barlamane wa annass":"البرلمان والناس","alhane 3chaqnaha":"ألحان عشقناها",
 "salon shehrazade":"صالون شهرزاد","ch hiwa ma3a choumicha":"شهيوة مع شميشة","al amana":"الأمانة",
 "asrar al mondial":"أسرار المونديال","bulletin meteo":"النشرة الجوية","journal amazigh":"الأخبار بالأمازيغية",
 "3ailti":"عائلتي","sir al morjane":"سر المرجان","bahr addalam":"بحر الظلام","qalb aswad":"قلب أسود",
 "mondial stories":"حكايات المونديال","info soir":"أخبار المساء","eco news":"أخبار الاقتصاد",
 "al massaiya":"المسائية","hikayat chama":"حكايات شامة",
 "jabha f rassou":"جبهة فراسو",

 "charqi ou gharbi":"شرقي أو غربي","charqi ou lgharbi":"شرقي أو غربي","soiree chaabi":"سهرة شعبية",
 "soiree cha3bi":"سهرة شعبية","attahssina":"التحصينة","at tahssina":"التحصينة",
 "priere du vendredi":"صلاة الجمعة","priere vendredi":"صلاة الجمعة","ayne lkebrite":"عين الكبريت",
 "ayn lkebrite":"عين الكبريت","wlad 3li":"ولاد علي","oulad 3li":"ولاد علي","jt arabe":"الأخبار بالعربية",
 "journal amazigh":"الأخبار بالأمازيغية","al massaiya":"المسائية","al dahira":"الظهيرة","rachid show":"رشيد شو",
 "moudawala":"مداولة","lmktoub":"المكتوب","dar nsa":"دار النسا","najm chaabi":"النجم الشعبي"}

# 2M title language policy: keep native French programme brands in French.
T2M_KEEP_FR={
 "info soir","bulletin meteo","meteo","eco news","econews","auto moto","planete foot","planète foot"
}
T2M_FORCE_AR={
 "les interventions des partis politiques":"مداخلات الأحزاب السياسية",
 "interventions des partis politiques":"مداخلات الأحزاب السياسية"
}

CHADA={
 "dandana":("دندنة","برنامج موسيقي على شدى تي في يستضيف فنانين ويتابع جديد أعمالهم، مع حوار وفقرات موسيقية."),
 "dandanah":("دندنة","برنامج موسيقي على شدى تي في يستضيف فنانين ويتابع جديد أعمالهم، مع حوار وفقرات موسيقية."),
 "l botola":("البطولة","برنامج رياضي يتابع أخبار كرة القدم المغربية وأبرز مباريات البطولة، مع التحليل والنقاش الرياضي."),
 "lbotola":("البطولة","برنامج رياضي يتابع أخبار كرة القدم المغربية وأبرز مباريات البطولة، مع التحليل والنقاش الرياضي."),
 "100 var":("100% VAR","مجلة رياضية لتحليل أخبار كرة القدم والمباريات، مع نقاشات فنية وتكتيكية وتركيز على الكرة المغربية."),
 "chada al ousra":("شدى الأسرة","برنامج اجتماعي وأسري يناقش قضايا الأسرة والمجتمع ويستضيف مختصين وضيوفاً."),
 "assahm":("السهم","برنامج حواري يتناول مواضيع الساعة وقضايا المجتمع مع ضيوف ونقاش."),
 "9hiwa ola atay":("قهيوة ولا أتاي","موعد خفيف يجمع الحوار والترفيه ومواضيع الحياة اليومية في أجواء مغربية."),
 "hbab rabab":("حباب رباب","برنامج ترفيهي وفني على شدى تي في مع فقرات متنوعة وضيوف."),
 "funny m3a nani":("فاني مع ناني","برنامج ترفيهي يقدم فقرات خفيفة ومواقف مرحة وضيوفاً متنوعين."),
 "din wa dounia":("دين ودنيا","برنامج ديني واجتماعي يتناول قضايا الحياة اليومية من منظور توعوي مبسط."),
 "mag info":("MAG INFO - الأخبار","موعد إخباري يقدم أبرز الأخبار والمستجدات الوطنية والدولية."),
 "chada cover":("شدى كوفر","برنامج موسيقي يسلط الضوء على المواهب والأصوات الجديدة."),}
HOSTS={"imad ntifi":"عماد النتيفي","fakherddine":"فخر الدين الرجحي","houssine chahb":"حسين شهب",
 "jamila ouyoub":"جميلة أيوب","sarah azmi":"سارة عزمي","imane bououlid":"إيمان بوعوليد الإدريسي"}

def log(x): print("[%s] %s"%(datetime.now(TZ).strftime("%F %T %Z"),x),flush=True)
def clean(x): return re.sub(r"\s+"," ",html.unescape(str(x or "")).replace("\xa0"," ")).strip()
def norm(x):
 x=clean(x).casefold().replace("’","'"); x="".join(c for c in unicodedata.normalize("NFKD",x) if not unicodedata.combining(c))
 return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9%]+"," ",x)).strip()
def ar(x): return bool(re.search(r"[\u0600-\u06ff]",str(x or "")))
def lang(x,default="ar"): return "ar" if ar(x) else ("fr" if re.search(r"[A-Za-zÀ-ÿ]",str(x or "")) else default)
def xdt(d): return d.strftime("%Y%m%d%H%M%S %z")

class Http:
 def __init__(self):
  self.s=(cloudscraper.create_scraper() if cloudscraper else requests.Session()); self.s.headers.update({"User-Agent":UA,"Accept-Language":"ar,fr;q=.9,en;q=.7"})
 def get(self,url,**kw):
  last=None
  for n in range(3):
   try:
    r=self.s.get(url,timeout=18,**kw); r.raise_for_status(); return r
   except Exception as e: last=e; time.sleep(.7*(n+1))
  raise last

@dataclass
class Event:
 channel:str; start:datetime; title:str; desc:str=""; stop:datetime|None=None; tl:str="ar"; dl:str="ar"; source:str=""

def _snrt_fallback_desc(cid,title):
 channel=SNRT_AR_NAMES.get(cid,CHANNELS.get(cid,cid))
 if "أخبار" in title or "الأخبار" in title:
  return "نشرة إخبارية على %s تقدم أبرز الأخبار والمستجدات."%channel
 if "طقس" in title or "النشرة الجوية" in title:
  return "نشرة الطقس على %s مع توقعات الأحوال الجوية."%channel
 return "برنامج «%s» يُعرض على %s."%(title,channel)

def _snrt_desc_from_row(cid,row,title,time_text,original_title=""):
 # Prefer the exact synopsis published by SNRT. The current site can place it
 # either inside a dedicated description node or as plain text in the row.
 candidates=[]
 for el in row.find_all(["p","div","span"]):
  classes=" ".join(el.get("class",[]) or []).casefold()
  if any(k in classes for k in ("description","desc","synopsis","resume","résumé","program-text","programme-text","grille-desc")):
   txt=clean(el.get_text(" ",strip=True))
   if txt:candidates.append(txt)
 full=clean(row.get_text(" ",strip=True))
 if full:candidates.append(full)
 # Some SNRT channel pages render the synopsis as a sibling block immediately
 # after grille-line instead of nesting it inside the programme row.
 sibling_count=0
 for sib in row.next_siblings:
  if getattr(sib,"name",None) is None:
   continue
  classes=" ".join(sib.get("class",[]) or []).casefold()
  if "grille-line" in classes.split():
   break
  txt=clean(sib.get_text(" ",strip=True))
  if not txt:
   continue
  if re.match(r"^[0-2]?\\d\\s*[Hh:]\\s*[0-5]\\d\\b",txt):
   break
  if len(txt)<=600:
   candidates.insert(0,txt)
   sibling_count+=1
  if sibling_count>=3:
   break
 for raw in candidates:
  desc=clean(raw)
  if time_text:
   desc=clean(desc.replace(clean(time_text)," ",1))
  for ttl in (original_title,title):
   if ttl:
    desc=clean(desc.replace(clean(ttl)," ",1))
  desc=re.sub(r"\b(?:SAT|TNT|HD|الآن|مباشر)\b"," ",desc,flags=re.I)
  desc=clean(desc).strip(" -–—|:")
  if len(desc)>=8 and norm(desc)!=norm(title) and norm(desc)!=norm(original_title):
   return desc
 return _snrt_fallback_desc(cid,title)

def _snrt_detail_desc(http,href,title=""):
 href=clean(href)
 if not href or href.startswith("#") or "javascript:" in href.casefold() or "jascript:" in href.casefold():
  return ""
 url=href if href.startswith("http") else "https://www.snrt.ma/"+href.lstrip("/")
 try:
  soup=BeautifulSoup(http.get(url,headers={"Referer":"https://www.snrt.ma/ar/"}).text,"lxml")
 except Exception:
  return ""
 candidates=[]
 for attrs in ({"name":"description"},{"property":"og:description"},{"name":"twitter:description"}):
  el=soup.find("meta",attrs=attrs)
  if el:
   txt=clean(el.get("content"))
   if txt:candidates.append(txt)
 # The current SNRT detail template also exposes the synopsis in this block.
 for el in soup.select(".carousel-program-info-content p, .carousel-program-info p, .field--name-body p"):
  txt=clean(el.get_text(" ",strip=True))
  if txt:candidates.append(txt)
 nt=norm(title)
 for desc in candidates:
  nd=norm(desc)
  if not desc or len(desc)<20 or nd==nt:
   continue
  # Reject generic site metadata/navigation if SNRT ever changes templates.
  if "الشركة الوطنية للإذاعة والتلفزة" in desc and len(desc)<80:
   continue
  return desc
 return ""

def _snrt_generic_desc(desc,title=""):
 d=clean(desc);n=norm(d);t=norm(title)
 return (
  not d or n==t or len(d)<35
  or d.startswith("برنامج «")
  or d.startswith("نشرة إخبارية على ")
  or d.startswith("نشرة الطقس على ")
 )

def _snrt_visible_descs(soup):
 # Build a date-agnostic lookup from the actual visible SNRT sequence.
 # Some channel pages emit "07H00 Title" in one text node, while others emit
 # separate time/title nodes. Support both forms.
 strings=[clean(x) for x in soup.stripped_strings if clean(x)]
 time_rx=re.compile(r"^([0-2]?\d)\s*[Hh:]\s*([0-5]\d)(?:\s+(.+))?$")
 day_rx=re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")
 footer={"الرئيسية","الشركة","القنوات","الوسيط","طلبات العروض","Régie publicitaire","Mentions légales"}
 noise={"الآن","SAT","TNT","Image"}
 out=defaultdict(list);i=0
 while i<len(strings):
  m=time_rx.match(strings[i])
  if not m:
   i+=1;continue
  hm="%02d:%02d"%(int(m.group(1)),int(m.group(2)))
  parts=[]
  tail=clean(m.group(3) or "")
  if tail and tail not in noise:
   parts.append(tail)
  j=i+1
  while j<len(strings) and not time_rx.match(strings[j]):
   txt=strings[j]
   if txt in footer:
    break
   if day_rx.search(txt):
    if parts:break
    j+=1;continue
   if txt not in noise:
    parts.append(txt)
   j+=1
  if parts:
   title=parts[0]
   desc=clean(" ".join(parts[1:]))
   if desc and norm(desc)!=norm(title):
    out[(hm,norm(title))].append(desc)
  i=max(j,i+1)
 return out

def _snrt_flat_events(cid,soup):
 # SNRT increasingly renders schedule metadata as a flat visible sequence:
 # date tabs, then repeated "time / title / synopsis" blocks. Parse that
 # representation as a second authoritative path so synopses are not lost
 # when the old grille-line markup changes.
 now=datetime.now(TZ)
 strings=[clean(x) for x in soup.stripped_strings if clean(x)]
 time_rx=re.compile(r"^([0-2]?\d)\s*[Hh:]\s*([0-5]\d)$")
 day_rx=re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")
 day_labels=[];day_positions=[]
 for pos,txt in enumerate(strings):
  m=day_rx.search(txt)
  if not m:continue
  try:
   d=datetime(now.year,int(m.group(2)),int(m.group(1))).date()
   if d<now.date()-timedelta(days=180):d=datetime(now.year+1,d.month,d.day).date()
   if d>now.date()+timedelta(days=180):d=datetime(now.year-1,d.month,d.day).date()
  except Exception:
   continue
  if abs((d-now.date()).days)<=14:
   day_positions.append(pos)
   if d not in day_labels:day_labels.append(d)
 # Ignore unrelated clock strings in the site header. The programme grid begins
 # after the cluster of visible date tabs.
 if not day_labels or not day_positions:
  return []
 first_time=next((pos for pos in range(max(day_positions)+1,len(strings)) if time_rx.match(strings[pos])),None)
 if first_time is None:
  return []

 footer={"الرئيسية","الشركة","القنوات","الوسيط","طلبات العروض","Régie publicitaire","Mentions légales"}
 noise={"الآن","SAT","TNT","Image"}
 raw=[];i=first_time
 while i<len(strings):
  m=time_rx.match(strings[i])
  if not m:
   i+=1;continue
  hr,mi=int(m.group(1)),int(m.group(2))
  if hr>23:
   i+=1;continue
  j=i+1;parts=[]
  while j<len(strings) and not time_rx.match(strings[j]):
   txt=strings[j]
   if txt in footer:
    break
   if not day_rx.search(txt) and txt not in noise:
    parts.append(txt)
   j+=1
  if parts:
   title=parts[0]
   desc=clean(" ".join(parts[1:]))
   if norm(desc)==norm(title):
    desc=""
   raw.append({"minutes":hr*60+mi,"hr":hr,"mi":mi,"title":title,"desc":desc})
  i=max(j,i+1)
 if not raw:
  return []

 # Split the visible sequence into day groups. Post-midnight rows stay attached
 # to the preceding broadcast day; a morning restart starts the next tab/day.
 groups=[[]];prev=None
 for item in raw:
  cur=item["minutes"];new_day=False
  if prev is not None:
   if prev<5*60 and cur>=5*60:
    new_day=True
   elif cur+4*60<prev and cur>=5*60:
    new_day=True
  if new_day:groups.append([])
  groups[-1].append(item);prev=cur
 groups=[g for g in groups if g]
 if not groups:return []
 dates=sorted(day_labels)[-len(groups):]
 if len(dates)!=len(groups):
  return []

 out=[]
 for day,group in zip(dates,groups):
  carry=False;prev=None
  for item in group:
   cur=item["minutes"]
   if prev is not None and cur+4*60<prev and cur<5*60:carry=True
   if prev is not None and prev<5*60 and cur>=5*60:carry=False
   evday=day+(timedelta(days=1) if carry and item["hr"]<5 else timedelta(0))
   start=morocco_wall_clock(evday,dtime(item["hr"],item["mi"]))
   original_title=item["title"]
   desc=item["desc"]
   title=original_title
   ctx=original_title+" "+desc
   if "الأخبار" in ctx or "الاخبار" in ctx:
    for k,v in NEWS.items():
     if k in ctx:
      title=v
      break
   if not desc:
    desc=_snrt_fallback_desc(cid,title)
   out.append(Event(cid,start,title,desc,None,"ar","ar","snrt-ar-flat"))
   prev=cur
 infer(out)
 return out

def _arryadia_fill(rows,hours=48,slot_hours=2):
 # Keep every real official event, then fill only uncovered windows.
 # This guarantees a usable current/next EPG even when SNRT leaves Arryadia blank.
 now=datetime.now(TZ)
 start=now.replace(minute=0,second=0,microsecond=0)
 end=now+timedelta(hours=max(1,hours))
 out=list(rows)
 for cid in ARR_IDS:
  real=sorted(
   [e for e in rows if e.channel==cid and e.stop and e.stop>start and e.start<end],
   key=lambda e:e.start
  )
  cursor=start
  gaps=[]
  for e in real:
   es=max(start,e.start); ee=min(end,e.stop)
   if es>cursor:gaps.append((cursor,es))
   if ee>cursor:cursor=ee
  if cursor<end:gaps.append((cursor,end))
  for gs,ge in gaps:
   cur=gs
   while cur<ge:
    stop=min(ge,cur+timedelta(hours=slot_hours))
    if stop<=cur:break
    out.append(Event(
     cid,cur,"Arryadia Programme",
     "برامج قناة الرياضية. يتم تحديث هذا الموعد تلقائياً عند توفر الجدول الرسمي.",
     stop,"fr","ar","arryadia-auto"
    ))
    cur=stop
 return out

def infer(rows):
 by=defaultdict(list)
 for e in rows: by[e.channel].append(e)
 for rr in by.values():
  rr.sort(key=lambda e:e.start)
  for i,e in enumerate(rr):
   # Repair missing or invalid stop times. Old LKG rows can contain stop<=start;
   # never let one malformed event poison the whole Morocco publication.
   if not e.stop or e.stop<=e.start:
    nxt=rr[i+1].start if i+1<len(rr) and rr[i+1].start>e.start else None
    e.stop=nxt if nxt else e.start+timedelta(hours=1)

def previous(path):
 if not path.exists(): return []
 try:
  raw=gzip.decompress(path.read_bytes()) if path.suffix==".gz" else path.read_bytes(); root=ET.fromstring(raw); out=[]
  for p in root.findall("programme"):
   def dt(v):
    raw=clean(v)
    parts=raw.split()
    if not parts or len(parts[0]) < 14:
     raise ValueError("invalid XMLTV datetime: %r"%raw)
    stamp=parts[0][:14]
    off=parts[1] if len(parts)>1 else "+0000"
    if len(off)==4 and off[0] in "+-":
     off=off+"0"
    if len(off)!=5 or off[0] not in "+-":
     raise ValueError("invalid XMLTV timezone: %r"%raw)
    return datetime.strptime(stamp+" "+off,"%Y%m%d%H%M%S %z").astimezone(TZ)
   t=p.find("title"); d=p.find("desc"); out.append(Event(p.get("channel"),dt(p.get("start")),t.text or "",d.text if d is not None else "",dt(p.get("stop")) if p.get("stop") else None,t.get("lang") or "ar",d.get("lang") if d is not None else "ar","old"))
  return out
 except Exception as e: log("Previous feed unreadable: %s"%e); return []

def valid(group,rows):
 now=datetime.now(TZ); rr=[e for e in rows if e.channel in GROUPS[group] and e.start<now+timedelta(days=8) and (e.stop or e.start+timedelta(hours=1))>now-timedelta(hours=12)]
 c=defaultdict(int)
 for e in rr:c[e.channel]+=1
 if group=="snrt": ok=sum(c[x] for x in GROUPS[group] if x!="AFLAM.ma")>=10 and sum(bool(c[x]) for x in GROUPS[group] if x!="AFLAM.ma")>=3
 elif group=="arryadia":
  # Do not accept a stale current-day page: require real future coverage.
  future=[e for e in rr if (e.stop or e.start+timedelta(hours=1))>now]
  fc=defaultdict(int)
  for e in future:fc[e.channel]+=1
  ok=len(future)>=6 and (fc["Arryadia_HD"]>=3 or fc["Arryadia_TNT"]>=3)
 elif group=="2m": ok=c["2M"]>=6
 elif group=="chada":
  future=sum(1 for e in rr if (e.stop or e.start+timedelta(hours=1))>now and e.start<now+timedelta(days=3))
  ok=future>=3
 else: ok=sum(c.values())>=6 and max(c.values() or [0])>=3
 return ok,"events=%d"%sum(c.values())

def google_ar(http,text):
 if not clean(text) or ar(text): return clean(text)
 try:
  r=http.get("https://translate.googleapis.com/translate_a/single",params={"client":"gtx","sl":"auto","tl":"ar","dt":"t","q":text}); data=r.json(); y=clean("".join(x[0] for x in data[0] if x and x[0])); return y if ar(y) else clean(text)
 except Exception:return clean(text)

def tr2m_title(http,title):
 raw=clean(title);n=norm(raw)
 if n in T2M_KEEP_FR:return raw
 if n in T2M_FORCE_AR:return T2M_FORCE_AR[n]
 if n in T2M:return T2M[n]
 # Deterministic policy: translate only the programme type, never invent an
 # Arabic title for an unknown proper name/brand.
 for pre,apre in (("serie marocaine","مسلسل مغربي"),("serie turque","مسلسل تركي"),("serie","مسلسل"),("film marocain","فيلم مغربي"),("film","فيلم"),("documentaire","وثائقي"),("rediffusion","إعادة")):
  if n.startswith(pre+" "):
   rest=raw[len(pre):].strip(" :-")
   rn=norm(rest)
   if rn in T2M_KEEP_FR:mapped=rest
   else:mapped=T2M_FORCE_AR.get(rn) or T2M.get(rn) or rest
   return apre+(" : "+mapped if mapped else "")
 return raw

def tr2m_desc(http,desc,category="",title=""):
 # Restore the stable 2M policy: category-aware Arabic descriptions, and only
 # translate a real synopsis when Telerama actually provides one.
 raw=clean(desc);cat=norm(category);ttl=norm(title)
 detailed=raw and len(raw)>=35 and norm(raw) not in {cat,ttl} and norm(raw)!=norm(category+" "+title)
 if detailed:
  y=google_ar(http,raw)
  if ar(y):return y
 if "meteo" in cat:return "نشرة جوية على قناة 2M تقدم توقعات الطقس ودرجات الحرارة."
 if "journal" in cat or "information" in cat:return "موعد إخباري على قناة 2M لمتابعة أبرز الأخبار والمستجدات."
 if "sport" in cat:return "برنامج رياضي على قناة 2M يتابع الأخبار والمنافسات الرياضية."
 if "serie" in cat or "feuilleton" in cat:return "مسلسل يُعرض على قناة 2M."
 if "film" in cat:return "فيلم يُعرض على قناة 2M."
 if "documentaire" in cat:return "برنامج وثائقي يُعرض على قناة 2M."
 if "debat" in cat:return "برنامج حواري على قناة 2M."
 if "theatre" in cat:return "عرض مسرحي يُعرض على قناة 2M."
 if "divertissement" in cat:return "برنامج ترفيهي يُعرض على قناة 2M."
 if "magazine" in cat:return "مجلة تلفزيونية تُعرض على قناة 2M."
 n=norm(title or desc)
 if "akhbar" in n or "info" in n or "journal" in n:return "موعد إخباري على قناة 2M."
 return "برنامج يُعرض على قناة 2M."

def _medi1_fallback_desc(cid,title):
 n=norm(title)
 if any(k in n for k in ("news","journal","akhbar","nashrat","flash")) or any(k in title for k in ("الأخبار","نشرة","المنتصف","حصاد اليوم")):
  return "موعد إخباري على قناة ميدي1 تيفي لمتابعة أبرز الأخبار والمستجدات."
 return "برنامج «%s» يُعرض على قناة ميدي1 تيفي."%title

def _parse_medi1_page(cid,text,day):
 soup=BeautifulSoup(text,"lxml")
 tre=re.compile(r"^([0-2]?\\d)[:hH]([0-5]\\d)\\s*(.*)$")
 exact=re.compile(r"^([0-2]?\\d)[:hH]([0-5]\\d)$")
 ctas={x.casefold() for x in (
  "صفحة البرنامج","صفحة النشرة","شاهد النشرات","شاهد البرنامج","التفاصيل","المزيد",
  "voir les jts","voir le programme","page de l'émission","en direct","المباشر",
  "البث المباشر","MEDI1TV Maghreb","MEDI1TV Arabic","MEDI1TV Afrique","Image")}
 stop_words={x.casefold() for x in (
  "الرئيسية","الأخبار","البرامج الإخبارية","برامج القناة","الحلقات الكاملة","أقوى اللحظات",
  "شبكة البث","ترددات البث","اتصل بنا","للإعلان","عن القناة","إشارات قانونية",
  "Actualités","Programmes","Replay","Moments forts","Grille","Fréquences","Contact","A propos",
  "Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche",
  "الإثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت","الأحد")}
 rows=[]

 # Primary path: current Medi1 programme cards. Many descriptions are published
 # directly inside the schedule link, so preserve them verbatim.
 prev=None;pday=day
 for a in soup.find_all("a"):
  pieces=[clean(x) for x in a.stripped_strings if clean(x)]
  if not pieces:continue
  m=tre.match(pieces[0]); only=exact.match(pieces[0]);payload=[]
  if only:
   h1,m1=int(only.group(1)),int(only.group(2));payload=pieces[1:]
  elif m:
   h1,m1=int(m.group(1)),int(m.group(2));payload=([clean(m.group(3))] if clean(m.group(3)) else [])+pieces[1:]
  else:continue
  payload=[x for x in payload if x.casefold() not in ctas and x.casefold() not in stop_words]
  if not payload:continue
  mins=h1*60+m1
  if prev is not None and mins+300<prev:pday+=timedelta(days=1)
  prev=mins
  title=payload[0]
  desc=clean(" ".join(x for x in payload[1:] if x!=title))
  if not desc:desc=_medi1_fallback_desc(cid,title)
  rows.append(Event(cid,morocco_wall_clock(pday,dtime(h1,m1)),title,desc,None,lang(title),lang(desc),"medi1-card"))

 # Secondary authoritative path: Medi1 sometimes renders the schedule as plain
 # text (time and title are not wrapped in an <a>). The old parser silently
 # dropped these rows. Parse the visible sequence and merge it with card rows.
 strings=[clean(x) for x in soup.stripped_strings if clean(x)]
 raw=[];i=0
 while i<len(strings):
  m=exact.match(strings[i])
  if not m:
   i+=1;continue
  h1,m1=int(m.group(1)),int(m.group(2))
  j=i+1;parts=[]
  while j<len(strings) and not exact.match(strings[j]):
   s=strings[j]
   sf=s.casefold()
   if sf in stop_words and parts:break
   if sf not in ctas and sf not in stop_words and not re.fullmatch(r"image",s,re.I):
    parts.append(s)
   j+=1
   if len(parts)>=8:break
  if parts:
   title=parts[0]
   desc=clean(" ".join(x for x in parts[1:] if x!=title))
   # Avoid swallowing navigation text when a programme has no synopsis.
   if len(desc)>800:desc=""
   raw.append((h1,m1,title,desc))
  i=max(j,i+1)

 prev=None;pday=day
 for h1,m1,title,desc in raw:
  mins=h1*60+m1
  if prev is not None and mins+300<prev:pday+=timedelta(days=1)
  prev=mins
  if not desc:desc=_medi1_fallback_desc(cid,title)
  rows.append(Event(cid,morocco_wall_clock(pday,dtime(h1,m1)),title,desc,None,lang(title),lang(desc),"medi1-flat"))

 # One programme per start/title. Prefer the richest official description.
 merged={}
 for e in rows:
  k=(e.start,e.title.casefold())
  prev=merged.get(k)
  if prev is None:
   merged[k]=e;continue
  pg=prev.desc.startswith("برنامج «") or prev.desc.startswith("موعد إخباري على قناة ميدي1")
  eg=e.desc.startswith("برنامج «") or e.desc.startswith("موعد إخباري على قناة ميدي1")
  if (pg and not eg) or (pg==eg and len(e.desc)>len(prev.desc)):
   merged[k]=e
 out=sorted(merged.values(),key=lambda e:e.start)
 infer(out)
 official=sum(1 for e in out if not (e.desc.startswith("برنامج «") or e.desc.startswith("موعد إخباري على قناة ميدي1")))
 log("Medi1 %s page events=%d official_desc=%d flat=%d"%(cid,len(out),official,sum(1 for e in out if e.source=="medi1-flat")))
 return out

def scrape_medi1(days):
 h=Http();out=[];today=datetime.now(TZ).date()
 for cid,bases in MEDI1:
  rows=[]
  for i in range(days):
   day=today+timedelta(days=i);ds=day.strftime("%d-%m-%Y");r=None
   for base in bases:
    try:
     r=h.get(base+"/"+ds,headers={"Referer":"https://www.medi1tv.com/ar/"})
     break
    except Exception:pass
   if r is None and i==0:
    for base in bases:
     try:
      r=h.get(base,headers={"Referer":"https://www.medi1tv.com/ar/"})
      break
     except Exception:pass
   if r is None:continue
   rows+=_parse_medi1_page(cid,r.text,day)
  seen={}
  for e in sorted(rows,key=lambda e:e.start):
   k=(e.start,e.title.casefold())
   prev=seen.get(k)
   if prev is None or len(e.desc or "")>len(prev.desc or ""):seen[k]=e
  out+=sorted(seen.values(),key=lambda e:e.start)
 infer(out)
 # Never publish a blank/title-only Medi1 description.
 for e in out:
  if not clean(e.desc) or norm(e.desc)==norm(e.title):
   e.desc=_medi1_fallback_desc(e.channel,e.title);e.dl="ar"
 return out

def _telerama_detail_desc(h,href,title=""):
 href=clean(href)
 if not href or href.startswith("#") or "javascript:" in href.casefold():
  return ""
 # Programme links are normally relative to television.telerama.fr; cinema
 # pages may redirect to www.telerama.fr and requests follows that safely.
 url=requests.compat.urljoin("https://television.telerama.fr/",href)
 try:
  soup=BeautifulSoup(h.get(url,headers={"Referer":"https://television.telerama.fr/"}).text,"lxml")
 except Exception:
  return ""
 candidates=[]
 # Prefer the explicit Synopsis block exposed by current Telerama programme pages.
 h2=soup.find(["h2","h3"],string=lambda x:x and clean(x).casefold()=="synopsis")
 if h2:
  p=h2.find_next("p")
  if p:
   txt=clean(p.get_text(" ",strip=True))
   if txt:candidates.append(txt)
 # Metadata fallback for template changes.
 for attrs in ({"property":"og:description"},{"name":"description"},{"name":"twitter:description"}):
  el=soup.find("meta",attrs=attrs)
  if el:
   txt=clean(el.get("content"))
   if txt:candidates.append(txt)
 nt=norm(title)
 for desc in candidates:
  nd=norm(desc)
  if not desc or len(desc)<20 or nd==nt:
   continue
  if desc.casefold().startswith(("programme tv","retrouvez le programme","telerama")):
   continue
  return desc
 return ""

def parse_2m(h,text,day,detail_cache=None):
 soup=BeautifulSoup(text,"lxml");out=[];seen=set()
 if detail_cache is None:detail_cache={}
 cats=("Magazine sportif","Documentaire de société","Magazine d'information",
       "Magazine de services","Magazine de société","Magazine culturel",
       "Série dramatique","Série sentimentale","Divertissement","Documentaire",
       "Feuilleton","Magazine","Journal","Météo","Débat","Théâtre","Film","Série")
 for a in soup.find_all("a"):
  parts=[clean(x) for x in a.stripped_strings if clean(x)]
  raw=clean(" ".join(parts))
  m=re.search(r"(?<!\d)([0-2]?\d)h([0-5]\d)(?!\d)",raw)
  if not m:continue
  prefix=clean(raw[:m.start()])
  category=""
  title=prefix
  for cat in sorted(cats,key=len,reverse=True):
   if prefix.casefold().startswith(cat.casefold()+" "):
    category=cat
    title=clean(prefix[len(cat):])
    break
  if not title or len(title)>120 or re.fullmatch(r"[0-2]?\d[h:]?[0-5]\d",title):continue
  k=("%02d:%02d"%(int(m.group(1)),int(m.group(2))),title.casefold())
  if k in seen:continue
  seen.add(k)
  hr,mi=int(m.group(1)),int(m.group(2))
  # Telerama's 2M grid is published one hour ahead of the actual Morocco
  # broadcast clock. Keep a fixed -1h correction here; do NOT convert through
  # Europe/Paris, otherwise summer time would incorrectly shift 13:45 to 11:45.
  source_dt=datetime.combine(day,dtime(hr,mi))-timedelta(hours=1)
  start=morocco_wall_clock(source_dt.date(),source_dt.time())

  # Same Morocco Cloud 2M logic: normalized Arabic title + translated/normalized description.
  # Prefer the real synopsis from the linked Telerama programme page, exactly as
  # SNRT now prefers its programme-detail synopsis over a generic fallback.
  desc=""
  href=clean(a.get("href")) if a else ""
  if href and (".php" in href or "/tele/" in href or "/cinema/" in href):
   if href not in detail_cache:
    detail_cache[href]=_telerama_detail_desc(h,href,title)
   desc=clean(detail_cache.get(href))
  if not desc and len(parts)>1:
   tail=[]
   passed_time=False
   for p in parts:
    if re.search(r"(?<!\d)[0-2]?\d[h:][0-5]\d(?!\d)",p):
     passed_time=True
     continue
    if passed_time and p!=title and p!=category:
     tail.append(p)
   desc=clean(" ".join(tail))
  if not desc:
   desc=category or title

  at=tr2m_title(h,title)
  ad=tr2m_desc(h,desc,category,title)
  out.append(Event("2M",start,at,ad,None,lang(at),"ar","2m-telerama"))
 out.sort(key=lambda e:e.start)
 return out

def scrape_2m(days):
 # Strict receiver policy: publish only the next 48 hours.
 # We may need up to 3 calendar pages when the run starts late in the day,
 # but events beyond now+48h are never kept.
 h=Http();now=datetime.now(TZ);today=now.date();target=now+timedelta(hours=48);out=[];detail_cache={}
 weekdays=["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
 page_days=(target.date()-today).days+1
 for i in range(page_days):
  d=today+timedelta(days=i)
  url="https://television.telerama.fr/chaine/2m-maroc" if i==0 else f"https://television.telerama.fr/programme-tv-{weekdays[d.weekday()]}/2m-maroc"
  try:
   rows=parse_2m(h,h.get(url,headers={"Referer":"https://television.telerama.fr/"}).text,d,detail_cache)
   log("2M %s telerama: %d events"%(d.isoformat(),len(rows)))
   out+=rows
  except Exception as ex:
   log("2M %s telerama failed: %s"%(d.isoformat(),ex))
 seen=set()
 out=[ev for ev in sorted(out,key=lambda ev:ev.start)
      if ev.start < target and not ((ev.start,ev.title.casefold()) in seen or seen.add((ev.start,ev.title.casefold())))]
 infer(out)
 out=[ev for ev in out if ev.stop and ev.stop>now-timedelta(hours=2) and ev.start<target and ev.stop>ev.start and ev.stop-ev.start<=timedelta(hours=4)]
 log("2M strict 48h total: %d events; detail_pages=%d; cutoff=%s"%(len(out),len(detail_cache),target.isoformat()))
 return out

def _chada_title_desc(raw):
 title=clean(raw).strip(" .-|:")
 n=norm(title)
 meta=next((CHADA[k] for k in sorted(CHADA,key=len,reverse=True) if k in n),None)
 if meta:return meta
 if "capsule sport" in n:return ("Capsule sport","Capsule sportive sur Chada TV.")
 if "capsule culinaire" in n:return ("Capsule culinaire","Capsule culinaire sur Chada TV.")
 if "capsule beaute" in n:return ("Capsule beauté","Capsule beauté sur Chada TV.")
 if "capsule mode" in n:return ("Capsule mode","Capsule mode sur Chada TV.")
 if "capsule bien etre" in n:return ("Capsule bien-être","Capsule bien-être sur Chada TV.")
 return (title,"Programme diffusé sur Chada TV.")

def _parse_chada_piisas(text,day):
 soup=BeautifulSoup(text,"lxml");raw=[]
 # Piisas renders each schedule item as a list row. Parse DOM rows first,
 # then fall back to every text node / raw HTML so minor markup changes
 # do not zero the feed.
 candidates=[]
 for el in soup.find_all(["li","p","div","span","a"]):
  t=clean(" ".join(el.stripped_strings))
  if t and re.search(r"\b[0-2]?\d:[0-5]\d\b",t):
   candidates.append(t)
 candidates.extend(clean(x) for x in soup.stripped_strings if x)
 candidates.append(clean(soup.get_text(" ",strip=True)))
 candidates.append(clean(re.sub(r"<[^>]+>"," ",text)))
 rx=re.compile(r"(?<!\d)([0-2]?\d:[0-5]\d)\s*(?:-|–|—|:|\u00a0)*\s*([^|\n]+?)(?=(?:\s+[0-2]?\d:[0-5]\d\b)|$)")
 for cand in candidates:
  for m in rx.finditer(cand):
   hm=clean(m.group(1));title=clean(m.group(2)).strip(" .-|–—:")
   # avoid swallowing navigation/footer text when a whole-page candidate is used
   title=re.split(r"\s+(?:HIER|CE MOMENT|AUJOURD.HUI|CE SOIR|DEMAIN)\b",title,1,flags=re.I)[0].strip()
   if len(title)<2 or len(title)>140:continue
   hr,mi=map(int,hm.split(":"))
   if hr>23:continue
   raw.append((morocco_wall_clock(day,dtime(hr,mi)),title))
 out=[];seen=set()
 for start,title in sorted(raw,key=lambda x:x[0]):
  k=(start,title.casefold())
  if k in seen:continue
  seen.add(k)
  t,d=_chada_title_desc(title)
  out.append(Event("Chada TV",start,t,d,None,lang(t,"fr"),lang(d,"fr"),"piisas"))
 infer(out)
 return out

def _scrape_chada_official(days):
 h=Http();today=datetime.now(TZ).date();out=[]
 try:r=h.get("https://chada.ma/fr/chada-tv/grille-tv/")
 except Exception:r=None
 if not r:return out
 tree=LH.fromstring(r.text)
 for bad in tree.xpath("//script|//style|//nav|//footer|//header"):
  if bad.getparent() is not None:bad.getparent().remove(bad)
 area=(tree.xpath("//div[contains(@class,'elementor-text-editor')]") or tree.xpath("//div[contains(@class,'posts-area')]") or tree.xpath("//body"))
 full="  ".join(clean(x) for x in area[0].xpath(".//text()") if clean(x)) if area else ""
 raw=[]
 for m in re.finditer(r"(\d{2}:\d{2})(?:\s*(?:à|-)\s*\d{2}:\d{2})?\s*[.\-]?\s*(.*?)(?=\s*(?:\d{2}:\d{2})|$)",full):
  title=clean(m.group(2)).strip(" .-|:")
  if len(title)>2:raw.append((datetime.strptime(m.group(1),"%H:%M").time(),title))
 seq=[];last=None
 for t,title in raw:
  if last is None or t>last or (t<last and last.hour>=18 and t.hour<=5):seq.append((t,title));last=t
 for i in range(min(days,1)):
  cur=today+timedelta(days=i);prev=seq[0][0] if seq else dtime(0)
  for t,orig in seq:
   if t<prev:cur+=timedelta(days=1)
   prev=t
   title,desc=_chada_title_desc(orig)
   out.append(Event("Chada TV",morocco_wall_clock(cur,t),title,desc,None,lang(title,"fr"),lang(desc,"fr"),"chada-official"))
 infer(out);return out

def scrape_chada(days):
 h=Http();today=datetime.now(TZ).date();out=[]
 pages=[(today,"https://piisas.com/chada-tv/aujourdhui")]
 if days>1:pages.append((today+timedelta(days=1),"https://piisas.com/chada-tv/demain"))
 for day,url in pages:
  try:
   rows=_parse_chada_piisas(h.get(url,headers={"Referer":"https://piisas.com/chada-tv/"}).text,day)
   log("Chada %s piisas: %d events"%(day.isoformat(),len(rows)))
   out+=rows
  except Exception as ex:
   log("Chada %s piisas failed: %s"%(day.isoformat(),ex))
 if not out:
  out=_scrape_chada_official(days)
  log("Chada official fallback: %d events"%len(out))
 seen=set();cleanrows=[]
 for ev in sorted(out,key=lambda ev:ev.start):
  k=(ev.start,ev.title.casefold())
  if k not in seen:
   seen.add(k);cleanrows.append(ev)
 infer(cleanrows)
 return cleanrows

def scrape_snrt(days):
 def one(cid,url):
  h=Http();r=h.get(url);soup=BeautifulSoup(r.text,"lxml");structured=[]
  visible=_snrt_visible_descs(soup);visible_used=defaultdict(int);visible_matches=0
  detail_cache={};detail_matches=0
  now=datetime.now(TZ);detail_from=now-timedelta(hours=12);detail_until=now+timedelta(days=min(max(days,1),3))
  for row in soup.find_all("div",class_=lambda x:x and "grille-line" in x.split()):
   dc=[x for x in row.get("class",[]) if x.isdigit() and len(x)==8]
   tt=row.find("div",class_="grille-time")
   if not dc or not tt:continue
   time_text=clean(tt.get_text())
   try:start=morocco_localize(datetime.strptime(dc[0]+" "+time_text.replace("H",":"),"%Y%m%d %H:%M"))
   except Exception:continue
   h2=row.find("h2",class_="program-title-sm")
   original_title=clean(h2.get_text(" ",strip=True)) if h2 else "برنامج"
   desc=_snrt_desc_from_row(cid,row,original_title,time_text,original_title)
   # Most current SNRT grids expose only time/title (or a genre badge). The
   # full official synopsis is on the linked programme page. Fetch it only for
   # the 48-72h working window and only when the row itself has no rich synopsis.
   if detail_from<=start<detail_until and _snrt_generic_desc(desc,original_title):
    a=h2.find_parent("a") if h2 else None
    href=clean(a.get("href")) if a else ""
    if href and "javascript:" not in href.casefold() and "jascript:" not in href.casefold():
     if href not in detail_cache:
      detail_cache[href]=_snrt_detail_desc(h,href,original_title)
     rich=clean(detail_cache.get(href))
     # _snrt_detail_desc already rejects empty/title-only/site-generic metadata.
     # Keep short official SNRT synopses too; some legitimate descriptions are
     # concise and should not be replaced by our generic fallback.
     if rich:
      desc=rich;detail_matches+=1
   tm=re.search(r"([0-2]?\d)\s*[Hh:]\s*([0-5]\d)",time_text)
   if tm:
    key=("%02d:%02d"%(int(tm.group(1)),int(tm.group(2))),norm(original_title))
    choices=visible.get(key,[])
    pos=visible_used[key]
    if pos<len(choices):
     vdesc=clean(choices[pos]);visible_used[key]+=1
     generic=(not desc or norm(desc)==norm(original_title) or desc.startswith("برنامج «") or desc.startswith("نشرة إخبارية على ") or desc.startswith("نشرة الطقس على "))
     if vdesc and (generic or len(vdesc)>len(desc)):
      desc=vdesc;visible_matches+=1
   title=original_title
   row_text=clean(row.get_text(" ",strip=True));ctx=original_title+" "+row_text+" "+desc
   if "الأخبار" in ctx or "الاخبار" in ctx:
    for k,v in NEWS.items():
     if k in ctx:
      title=v
      break
   structured.append(Event(cid,start,title,desc,None,"ar","ar","snrt-ar"))

  flat=_snrt_flat_events(cid,soup)
  # One programme per channel/start. Prefer an official non-generic synopsis;
  # when both parsers found it, keep the richer description.
  merged={}
  def score(e):
   d=clean(e.desc)
   generic=(not d or norm(d)==norm(e.title) or d.startswith("برنامج «") or d.startswith("نشرة إخبارية على ") or d.startswith("نشرة الطقس على "))
   return (0 if generic else 1,len(d),1 if e.source=="snrt-ar-flat" else 0)
  for e in structured+flat:
   prev=merged.get(e.start)
   if prev is None or score(e)>score(prev):
    merged[e.start]=e
  rows=sorted(merged.values(),key=lambda e:e.start)
  infer(rows)
  official=sum(1 for e in rows if score(e)[0])
  log("SNRT %s structured=%d flat=%d merged=%d official_desc=%d detail_matches=%d detail_pages=%d visible_matches=%d visible_keys=%d"%(cid,len(structured),len(flat),len(rows),official,detail_matches,len(detail_cache),visible_matches,len(visible)))
  return rows

 out=[]
 with ThreadPoolExecutor(max_workers=5) as ex:
  fs={ex.submit(one,c,u):c for c,u in SNRT.items()}
  for f in as_completed(fs):
   try:out+=f.result()
   except Exception as e:log("SNRT %s: %s"%(fs[f],e))
 start=datetime.now(TZ).replace(hour=0,minute=0,second=0,microsecond=0)
 for i in range(days*8):
  out.append(Event(
   "AFLAM.ma",start+timedelta(hours=3*i),"برامج قناة السابعة AFLAM",
   "أفضل الأفلام والبرامج السينمائية على القناة السابعة المغربية",
   start+timedelta(hours=3*(i+1)),"ar","ar","snrt"
  ))
 infer(out)
 # Never publish a blank SNRT description.
 for e in out:
  if not clean(e.desc):e.desc=_snrt_fallback_desc(e.channel,e.title)
 return out

def _arryadia_date_token(raw,now):
 raw=clean(raw)
 candidates=[]
 for fmt in ("%Y%m%d","%d%m%Y"):
  try:candidates.append(datetime.strptime(raw,fmt).date())
  except Exception:pass
 if not candidates:return None
 # Accept only dates close to the current guide window. This prevents stale
 # hidden/archive markup from being published as current EPG.
 candidates.sort(key=lambda d:abs((d-now.date()).days))
 return candidates[0] if abs((candidates[0]-now.date()).days)<=10 else None

def _arryadia_date_from_node(node,now):
 cur=node
 for _ in range(8):
  if cur is None:break
  vals=[]
  try:
   vals.extend(cur.get("class",[]) or [])
   for key in ("id","data-date","data-day","data-dt"):
    v=cur.get(key)
    if v:vals.append(v)
  except Exception:pass
  for value in vals:
   for tok in re.findall(r"(?<!\d)\d{8}(?!\d)",str(value)):
    d=_arryadia_date_token(tok,now)
    if d:return d
  cur=getattr(cur,"parent",None)
 return None

def _arryadia_event_container(node):
 # Find the smallest useful parent containing time + title/description.
 cur=node
 best=getattr(node,"parent",None)
 for _ in range(6):
  cur=getattr(cur,"parent",None)
  if cur is None:break
  txt=clean(cur.get_text(" ",strip=True))
  if 8<=len(txt)<=700:best=cur
  if cur.name in ("li","article","tr"):break
  classes=" ".join(cur.get("class",[]) or []).lower()
  if any(k in classes for k in ("grille-line","program","programme","schedule","item")):break
 return best or getattr(node,"parent",node)

def _parse_arryadia_snrt(soup):
 now=datetime.now(TZ);raw=[];seen=set()
 # Scan every visible time token rather than only the old div.grille-line
 # markup. SNRT now mixes old rows and a newer card-style layout.
 time_rx=re.compile(r"^\s*([0-2]?\d)\s*[Hh:]\s*([0-5]\d)\s*$")
 for txtnode in soup.find_all(string=True):
  t=clean(txtnode)
  m=time_rx.match(t)
  if not m:continue
  day=_arryadia_date_from_node(txtnode,now)
  if not day:continue
  hr,mi=int(m.group(1)),int(m.group(2))
  if hr>23:continue
  box=_arryadia_event_container(txtnode)
  # Prefer an explicit heading/link for the programme title.
  title=""
  if box is not None:
   cand=box.find(["h1","h2","h3","h4","a"],string=lambda x:x and clean(x) and not time_rx.match(clean(x)))
   if cand:title=clean(cand.get_text(" ",strip=True))
  parts=[clean(x) for x in box.stripped_strings if clean(x)] if box is not None else []
  parts=[x for x in parts if not time_rx.match(x) and x not in ("الآن","SAT","TNT")]
  if not title and parts:title=parts[0]
  if not title or len(title)>220:continue
  desc=clean(" ".join(x for x in parts if x!=title))
  s=morocco_wall_clock(day,dtime(hr,mi))
  key=(s,title.casefold())
  if key in seen:continue
  seen.add(key);raw.append((s,title,desc or title))
 # Keep the legacy row parser as a compatibility supplement.
 for row in soup.find_all("div",class_=lambda x:x and "grille-line" in x.split()):
  vals=[]
  vals.extend(row.get("class",[]) or [])
  for key in ("id","data-date","data-day","data-dt"):
   v=row.get(key)
   if v:vals.append(v)
  day=None
  for value in vals:
   for tok in re.findall(r"(?<!\d)\d{8}(?!\d)",str(value)):
    day=_arryadia_date_token(tok,now)
    if day:break
   if day:break
  tt=row.find(class_=lambda x:x and "grille-time" in " ".join(x if isinstance(x,list) else [x]))
  if not day or not tt:continue
  m=re.search(r"([0-2]?\d)\s*[Hh:]\s*([0-5]\d)",clean(tt.get_text()))
  if not m:continue
  s=morocco_wall_clock(day,dtime(int(m.group(1)),int(m.group(2))))
  h2=row.find(["h2","h3"],class_=lambda x:x and "program" in " ".join(x if isinstance(x,list) else [x]).lower())
  title=clean(h2.get_text(" ",strip=True)) if h2 else ""
  if not title:continue
  desc=clean(row.get_text(" ",strip=True)) or title
  key=(s,title.casefold())
  if key not in seen:seen.add(key);raw.append((s,title,desc))
 raw.sort(key=lambda x:x[0])
 return raw

def _parse_arryadia_flat(soup):
 # Current SNRT page keeps the day tabs together, then emits programme blocks
 # in DOM order. Parse that official text layout when date attributes are not
 # attached to each programme row.
 now=datetime.now(TZ)
 strings=[clean(x) for x in soup.stripped_strings if clean(x)]
 time_rx=re.compile(r"^([0-2]?\d)\s*[Hh:]\s*([0-5]\d)$")
 day_rx=re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")
 day_labels=[]
 first_time=None
 for pos,s in enumerate(strings):
  if first_time is None and time_rx.match(s):first_time=pos
  if first_time is not None and pos>=first_time:break
  m=day_rx.search(s)
  if not m:continue
  try:
   d=datetime(now.year,int(m.group(2)),int(m.group(1))).date()
   if d<now.date()-timedelta(days=180):d=datetime(now.year+1,d.month,d.day).date()
   if d>now.date()+timedelta(days=180):d=datetime(now.year-1,d.month,d.day).date()
  except Exception:continue
  if d not in day_labels:day_labels.append(d)
 if first_time is None or not day_labels:return []

 # Build programme blocks: one time token followed by title/description text.
 raw=[]
 i=first_time
 while i<len(strings):
  m=time_rx.match(strings[i])
  if not m:
   i+=1;continue
  hr,mi=int(m.group(1)),int(m.group(2))
  if hr>23:i+=1;continue
  j=i+1;parts=[]
  while j<len(strings) and not time_rx.match(strings[j]):
   s=strings[j]
   if s in ("الرئيسية","الشركة","القنوات","الوسيط","طلبات العروض","Régie publicitaire","Mentions légales"):
    break
   if not day_rx.search(s):parts.append(s)
   j+=1
  # Keep channel markers for feed selection but not as the visible title.
  visible=[x for x in parts if x not in ("الآن","SAT","TNT") and not re.fullmatch(r"Image",x,re.I)]
  if visible:
   title=visible[0]
   desc=clean(" ".join(visible[1:])) or title
   markers=" ".join(parts)
   raw.append({"minutes":hr*60+mi,"hr":hr,"mi":mi,"title":title,"desc":desc,"markers":markers})
  i=max(j,i+1)
 if not raw:return []

 # Split the flat list into daily blocks. A morning restart after a daytime
 # schedule, or after post-midnight carry-over, starts the next visible day.
 groups=[[]]
 prev=None
 for item in raw:
  cur=item["minutes"]
  new_day=False
  if prev is not None:
   if prev<5*60 and cur>=5*60:
    new_day=True
   elif cur+4*60<prev and cur>=5*60:
    new_day=True
  if new_day:groups.append([])
  groups[-1].append(item);prev=cur
 groups=[g for g in groups if g]
 if not groups:return []

 # SNRT can omit an expired first day from the programme DOM while leaving its
 # tab visible. Align the visible programme groups to the most recent day tabs.
 dates=sorted(day_labels)[-len(groups):]
 if len(dates)!=len(groups):return []
 out=[]
 for day,group in zip(dates,groups):
  carry=False;prev=None
  for item in group:
   cur=item["minutes"]
   if prev is not None and cur+4*60<prev and cur<5*60:carry=True
   if prev is not None and prev<5*60 and cur>=5*60:carry=False
   evday=day+(timedelta(days=1) if carry and item["hr"]<5 else timedelta(0))
   s=morocco_wall_clock(evday,dtime(item["hr"],item["mi"]))
   full=(item["title"]+" "+item["desc"]+" "+item["markers"]).lower()
   ids=[]
   if re.search(r"\btnt\b",full):ids.append("Arryadia_TNT")
   if re.search(r"\bsat\b",full):ids.append("Arryadia_HD")
   if not ids:ids=["Arryadia_HD","Arryadia_TNT"]
   title=item["title"]
   if re.search(r"\b(?:direct|live)\b|مباشر",full,re.I) and not title.startswith("مباشر"):
    title="مباشر: "+title
   for cid in ids:out.append(Event(cid,s,title,item["desc"],None,"ar","ar","arryadia-snrt-flat"))
   prev=cur
 infer(out)
 log("Arryadia flat parser groups=%d dates=%s events=%d"%(len(groups),",".join(d.isoformat() for d in dates),len(out)))
 return out

def scrape_arryadia(days):
 h=Http();parsed=[];flat=[]
 try:
  r=h.get("https://www.snrt.ma/ar/node/4070",
          params={"_":int(time.time())},
          headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
                   "Accept-Language":"ar-MA,ar;q=.9,fr;q=.8,en;q=.6",
                   "Cache-Control":"no-cache","Pragma":"no-cache"})
  soup=BeautifulSoup(r.text,"lxml")
  structured=_parse_arryadia_snrt(soup)
  flat=_parse_arryadia_flat(soup)
  # Keep legacy tuples and visible-layout Event objects separate; they are
  # normalized to Event below before de-duplication.
  parsed=structured
 except Exception as e:log("Arryadia SNRT parse: %s"%e)
 if parsed:
  log("Arryadia SNRT parsed=%d range=%s..%s"%(len(parsed),parsed[0][0].isoformat(),parsed[-1][0].isoformat()))
 else:
  log("Arryadia SNRT parsed=0")
  # Diagnostic for SNRT markup changes: log only structural attributes around
  # a few time tokens, never the full response.
  try:
   shown=0
   trx=re.compile(r"^\s*[0-2]?\d\s*[Hh:]\s*[0-5]\d\s*$")
   for tn in soup.find_all(string=True):
    if not trx.match(clean(tn)):continue
    chain=[];cur=getattr(tn,"parent",None)
    for _ in range(6):
     if cur is None:break
     attrs=[]
     for k in ("class","id","data-date","data-day","data-dt"):
      v=cur.get(k)
      if v:attrs.append("%s=%s"%(k,v))
     chain.append("%s[%s]"%(getattr(cur,"name","?"),",".join(attrs)))
     cur=getattr(cur,"parent",None)
    log("Arryadia DOM %s :: %s"%(clean(tn)," > ".join(chain)))
    shown+=1
    if shown>=12:break
  except Exception as de:log("Arryadia DOM diagnostic failed: %s"%de)
 out=[]
 for i,(s,title,desc) in enumerate(parsed):
  next_start=parsed[i+1][0] if i+1<len(parsed) else None
  stop=next_start if next_start and next_start>s and next_start-s<=timedelta(hours=6) else s+timedelta(hours=2)
  full=(title+" "+desc).lower()
  ids=[cid for pat,cid in ARR_TAGS.items() if re.search(pat,full)] or ["Arryadia_HD","Arryadia_TNT"]
  live=bool(re.search(r"\b(?:live|direct)\b|مباشر",full,re.I))
  if live and not title.startswith("مباشر"):title="مباشر: "+title
  for cid in ids:out.append(Event(cid,s,title,desc or title,stop,"ar","ar","arryadia-snrt"))
 out+=flat
 # De-duplicate rows exposed by both official SNRT layouts.
 dedup={}
 for e in out:
  k=(e.channel,e.start,e.title.casefold())
  prev=dedup.get(k)
  if prev is None or len(e.desc or "")>len(prev.desc or ""):dedup[k]=e
 out=sorted(dedup.values(),key=lambda e:(e.channel,e.start,e.title.casefold()))
 infer(out)
 now=datetime.now(TZ);limit=now+timedelta(days=min(days,3))
 current=[e for e in out if e.stop and e.stop>now-timedelta(hours=2) and e.start<limit and e.stop>e.start]
 future=[e for e in current if e.stop>now]
 log("Arryadia SNRT future=%d current_window=%d"%(len(future),len(current)))
 filled=_arryadia_fill(current,hours=48,slot_hours=2)
 auto_count=sum(1 for e in filled if e.source=="arryadia-auto")
 log("Arryadia auto filler=%d total=%d"%(auto_count,len(filled)))
 return filled

def to_xml(rows,path):
 # Final XMLTV safety gate: malformed timestamps must never poison the whole
 # Morocco feed. infer() repairs most cases; any remaining invalid row is
 # discarded here and reported in logs.
 valid_rows=[];dropped=0
 for e in rows:
  if not e.start or not e.stop or e.stop<=e.start:
   dropped+=1
   continue
  valid_rows.append(e)
 if dropped: log("Morocco XML safety gate dropped %d invalid rows"%dropped)
 root=ET.Element("tv",{"generator-info-name":"EPGManager Morocco Cloud rc23"});counts=defaultdict(int)
 for cid in sorted({e.channel for e in valid_rows}):ch=ET.SubElement(root,"channel",{"id":cid});ET.SubElement(ch,"display-name").text=CHANNELS.get(cid,cid)
 for e in sorted(valid_rows,key=lambda e:(e.start,e.channel,e.title)):
  p=ET.SubElement(root,"programme",{"start":xdt(e.start),"stop":xdt(e.stop),"channel":e.channel});ET.SubElement(p,"title",{"lang":e.tl or lang(e.title)}).text=e.title;ET.SubElement(p,"desc",{"lang":e.dl or lang(e.desc)}).text=e.desc or e.title;counts[e.channel]+=1
 ET.indent(root,space="  ");ET.ElementTree(root).write(path,encoding="utf-8",xml_declaration=True);return dict(counts)

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output-dir",default="output");ap.add_argument("--previous",default="");ap.add_argument("--days",type=int,default=7);ap.add_argument("--scheduled",action="store_true");a=ap.parse_args();now=datetime.now(TZ)
 if a.scheduled and now.hour not in (6,18):log("Schedule gate skip: local hour %02d"%now.hour);return 0
 outdir=Path(a.output_dir);outdir.mkdir(parents=True,exist_ok=True);old=previous(Path(a.previous)) if a.previous else [];results={};jobs={"snrt":lambda:scrape_snrt(a.days),"arryadia":lambda:scrape_arryadia(min(a.days,3)),"2m":lambda:scrape_2m(a.days),"chada":lambda:scrape_chada(a.days),"medi1":lambda:scrape_medi1(a.days)}
 with ThreadPoolExecutor(max_workers=4) as ex:
  fs={ex.submit(fn):name for name,fn in jobs.items()}
  for f in as_completed(fs):
   try:results[fs[f]]=f.result()
   except Exception as e:log("%s crashed: %s"%(fs[f],e));results[fs[f]]=[]
 final=[];status={}
 for g in ("snrt","arryadia","2m","chada","medi1"):
  rr=results.get(g,[]);ok,detail=valid(g,rr);mode="fresh"
  if not ok:
   rr=[e for e in old if e.channel in GROUPS[g]];ok,od=valid(g,rr);mode="last-known-good";detail+="; fallback="+od
  if g=="chada" and not ok:
   # Chada is optional. A stale/empty grid must not block Morocco or inject
   # obsolete programmes into the published feed.
   status[g]={"mode":"optional-missing","events":0,"detail":detail}
   log("chada: no valid future schedule; omitted")
   continue
  if not ok:
   log("FATAL %s invalid and no Last Known Good (%s)"%(g,detail));return 2
  final+=rr;status[g]={"mode":mode,"events":len(rr),"detail":detail};log("%s: %s (%s)"%(g,mode,detail))
 seen=set();merged=[]
 for e in sorted(final,key=lambda e:(e.channel,e.start,e.title.casefold())):
  k=(e.channel,xdt(e.start),e.title.casefold())
  if k not in seen:seen.add(k);merged.append(e)
 infer(merged);xml=outdir/"morocco.xml";counts=to_xml(merged,xml);raw=xml.read_bytes();gz=outdir/"morocco.xml.gz"
 with gzip.GzipFile(filename="morocco.xml",mode="wb",fileobj=gz.open("wb"),compresslevel=9,mtime=0) as f:f.write(raw)
 (outdir/"morocco.txt").write_text("\n".join("%s | %s | %d programmes"%(cid,CHANNELS.get(cid,cid),counts.get(cid,0)) for cid in sorted(CHANNELS))+"\n",encoding="utf-8")
 manifest={"version":now.strftime("%Y%m%d-%H%M%S"),"generated":now.isoformat(),"timezone":"Africa/Casablanca","url":"morocco.xml.gz","sha256":hashlib.sha256(gz.read_bytes()).hexdigest(),"size":gz.stat().st_size,"channels":len(counts),"programmes":sum(counts.values()),"channel_counts":counts,"sources":status}
 (outdir/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");log("PASS: %d channels / %d programmes / %.1f KiB"%(manifest["channels"],manifest["programmes"],manifest["size"]/1024));return 0
if __name__=="__main__":raise SystemExit(main())
