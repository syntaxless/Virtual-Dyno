"""Weather-lookup scenarios (place name, coordinates, old/future dates, API failures, timeouts, stale
responses, geolocation, GPS vs. log-only forms). Open-Meteo is mocked, so it needs no network.

  DYNO_LOG=/path/to/accessport.csv python tools/weather.py            # compare against the saved snapshot
  DYNO_LOG=/path/to/accessport.csv python tools/weather.py --update   # re-save the snapshot after an intended change

The output is deterministic, so it is stored in tools/data/weather_expected.txt and diffed. It takes ~25 s.
Review the diff before using --update: every changed line is a behaviour change.
"""
import asyncio, json, sys, re, os, difflib, builtins
from playwright.async_api import async_playwright
from common import URL, LOG, GPX, TOOLS, init_script

if not LOG:
    sys.exit("Set DYNO_LOG=/path/to/accessport.csv (the suite needs a real Accessport log).")
INIT = init_script(expand=True)
EXPECTED = TOOLS / "data" / "weather_expected.txt"
_lines = []


def print(*a, **k):                      # capture everything printed so it can be diffed
    s = " ".join(str(x) for x in a)
    _lines.append(s)
    builtins.print(s, flush=True)
CORS={'access-control-allow-origin':'*','content-type':'application/json'}
def fc(day='2026-10-01'):
    y,mo,d=map(int,day.split('-'));t=[];rh=[];ws=[];wd=[]
    for dd in (d,d+1):
        for h in range(24):
            t.append(f'{y}-{mo:02d}-{dd:02d}T{h:02d}:00');rh.append(40);ws.append(3);wd.append(180)
    rh[11]=31;ws[11]=6;wd[11]=270;rh[12]=33;ws[12]=8;wd[12]=300
    return json.dumps({'latitude':39.74,'longitude':-104.98,'elevation':1600,'utc_offset_seconds':-21600,'hourly':{'time':t,'relative_humidity_2m':rh,'wind_speed_10m':ws,'wind_direction_10m':wd}})
DEN=json.dumps({'results':[{'id':5419384,'name':'Denver','latitude':39.7392,'longitude':-104.9847,'elevation':1600,'timezone':'America/Denver','country':'United States','admin1':'Colorado'}]})
async def main():
    async with async_playwright() as pw:
        b=await pw.chromium.launch();errs=[];reqs=[]
        ctx=await b.new_context(viewport={'width':1200,'height':900},reduced_motion='reduce',permissions=['geolocation'],geolocation={'latitude':39.7392,'longitude':-104.9847})
        pg=await ctx.new_page()
        pg.on('pageerror',lambda e:errs.append(str(e)))
        pg.on('console',lambda m:errs.append(m.text) if m.type=='error' and 'ERR_' not in m.text and 'Failed to load' not in m.text else None)
        pg.on('request',lambda r:reqs.append(r.url) if 'open-meteo' in r.url else None)
        await pg.add_init_script(INIT)
        mode={'geo':'ok','fc':'ok','delay':0}
        async def h(route):
            u=route.request.url
            if mode['delay']:await asyncio.sleep(mode['delay'])
            k='geo' if 'geocoding-api' in u else 'fc';m=mode[k]
            if m=='hang':await asyncio.sleep(30);return
            if m=='fail':await route.abort('failed');return
            if m=='500':await route.fulfill(status=500,headers=CORS,body='{}');return
            if m=='junk':await route.fulfill(status=200,headers=CORS,body='<html>');return
            if k=='geo':await route.fulfill(status=200,headers=CORS,body='{"generationtime_ms":0.5}' if m=='none' else DEN)
            else:
                day=re.search(r'start_date=([\d-]+)',u).group(1);await route.fulfill(status=200,headers=CORS,body=fc(day))
        await pg.route('**/*open-meteo.com/**',h)
        vis=lambda s:pg.evaluate(f"!document.querySelector('{s}').hidden")
        msg=lambda:pg.inner_text('#wxmsg')
        async def place(q,date,time='11:00',wait=700):
            await pg.fill('#wxplace',q);await pg.fill('#wxdate',date);await pg.fill('#wxtime',time);await pg.click('#wxpget');await pg.wait_for_timeout(wait)
        await pg.goto(URL);await pg.wait_for_timeout(300)
        print('no data: weather block visible =',await vis('#wx'))
        await pg.set_input_files('#file',LOG);await pg.wait_for_timeout(2300)
        print('LOG ONLY: wx',await vis('#wx'),'| place form',await vis('#wxpl'),'| gps block',await vis('#wxgps'),'| manual paste',await vis('#wxman'),'| requests',len(reqs))
        base=[await pg.inner_text(f'#s{i} .n') for i in (1,2,3)];print('baseline',base)
        # 1 place name, heading unknown -> humidity only
        await place('Denver','2026-10-01')
        print('1 NAME  ->',await msg());print('   humid',await pg.input_value('#humid'),'wind',await pg.input_value('#wind'),'wdir',await pg.input_value('#wdir'))
        print('   requests:',[re.sub(r'&hourly=[^&]*','',u).replace('https://','')[:150] for u in reqs[-2:]])
        # 2 heading known -> wind applied
        await pg.fill('#head','75');await pg.click('#wxpget');await pg.wait_for_timeout(700)
        print('2 HEADING SET ->',await msg());print('   humid',await pg.input_value('#humid'),'wind',await pg.input_value('#wind'),'wdir',await pg.input_value('#wdir'),'| nums',[await pg.inner_text(f'#s{i} .n') for i in (1,2,3)])
        # 3 interpolation 11:30
        await place('Denver','2026-10-01','11:30');print('3 11:30 ->',await msg()[:0] if False else (await msg())[:120])
        # 4 coordinates, no geocode call
        n=len(reqs);await place('40.01, -105.27','2026-10-01','11:00');new=reqs[n:]
        print('4 COORDS ->',(await msg())[:100],'| geocode calls:',sum('geocoding' in u for u in new),'| forecast url:',re.sub(r'&hourly=[^&]*','',new[-1]).replace('https://','')[:140])
        # 5 older date -> archive
        n=len(reqs);await place('Denver','2026-03-01');print('5 OLD DATE -> endpoint:',re.search(r'//([^/]+/v1/\w+)',reqs[-1]).group(1),'|',(await msg())[:80])
        # 6 errors
        mode['geo']='none';await place('Nowhereville xyz','2026-10-01');print('6 NO RESULT ->',await msg())
        mode['geo']='500';await place('Denver','2026-10-01');print('7 GEO 500   ->',await msg())
        mode['geo']='fail';await place('Denver','2026-10-01');print('8 GEO FAIL  ->',await msg())
        mode['geo']='junk';await place('Denver','2026-10-01');print('9 GEO JUNK  ->',await msg())
        mode['geo']='ok';mode['fc']='500';await place('Denver','2026-10-01');print('10 FC 500   ->',await msg())
        mode['fc']='fail';await place('Denver','2026-10-01');print('11 FC FAIL  ->',await msg())
        mode['fc']='junk';await place('Denver','2026-10-01');print('12 FC JUNK  ->',await msg())
        mode['fc']='ok'
        await pg.fill('#wxplace','');await pg.click('#wxpget');await pg.wait_for_timeout(200);print('13 NO PLACE ->',await msg())
        await pg.fill('#wxplace','Denver');await pg.fill('#wxdate','');await pg.click('#wxpget');await pg.wait_for_timeout(200);print('14 NO DATE  ->',await msg())
        await place('Denver','2027-12-31',wait=300);print('15 FUTURE   ->',await msg())
        await place('95, 20','2026-10-01',wait=300);print('16 BAD LAT  ->',await msg())
        await place('Denver','2026-09-01',wait=700);
        # 17 wrong day returned
        # 18 enter key
        await pg.fill('#wxplace','Denver');await pg.fill('#wxdate','2026-10-01');await pg.fill('#wxtime','12:00');await pg.press('#wxplace','Enter');await pg.wait_for_timeout(700);print('17 ENTER KEY ->',(await msg())[:90])
        # 19 timeout
        mode['geo']='hang';await place('Denver','2026-10-01',wait=10800);print('18 TIMEOUT  ->',await msg(),'| button enabled',not await pg.evaluate("document.getElementById('wxpget').disabled"))
        mode['geo']='ok'
        # 20 stale: slow fetch, then load a new log mid-flight
        await pg.fill('#humid','25');mode['delay']=1.2;await pg.fill('#wxplace','Denver');await pg.click('#wxpget');await pg.wait_for_timeout(250)
        await pg.set_input_files('#file',LOG);await pg.wait_for_timeout(2600);mode['delay']=0
        print('19 STALE (new log mid-flight) -> humid',await pg.input_value('#humid'),'(expect 25 untouched) | msg:',repr(await msg()),'| button enabled',not await pg.evaluate("document.getElementById('wxpget').disabled"))
        # 21 geolocation
        await pg.fill('#wxplace','');await pg.click('#wxgeo');await pg.wait_for_timeout(700);print('20 GEOLOCATION ->',await pg.input_value('#wxplace'),'|',await msg())
        # 22 gps attached -> forms swap
        await pg.set_input_files('#gps',GPX);await pg.wait_for_timeout(2300)
        print('GPS ATTACHED: place form',await vis('#wxpl'),'| gps block',await vis('#wxgps'),'| manual paste',await vis('#wxman'))
        await pg.click('#wxget');await pg.wait_for_timeout(800);print('   gps fetch ->',(await msg())[:110])
        # denied geolocation in a fresh context
        c2=await b.new_context(viewport={'width':1200,'height':900},permissions=[]);p2=await c2.new_page();await p2.add_init_script(INIT)
        await p2.goto(URL);await p2.set_input_files('#file',LOG);await p2.wait_for_timeout(1500);await p2.click('#wxgeo');await p2.wait_for_timeout(1200)
        print('21 GEOLOCATION DENIED ->',await p2.inner_text('#wxmsg'))
        # GPS-only
        c3=await b.new_context(viewport={'width':1200,'height':900});p3=await c3.new_page();await p3.add_init_script(INIT);await p3.goto(URL)
        await p3.set_input_files('#gps',GPX);await p3.wait_for_timeout(2300)
        print('GPS ONLY: place form',not await p3.evaluate("document.getElementById('wxpl').hidden"),'| gps block',not await p3.evaluate("document.getElementById('wxgps').hidden"))
        # bad file after good -> hide
        await pg.reload();await pg.wait_for_timeout(300);await pg.set_input_files('#file',LOG);await pg.wait_for_timeout(1500)
        await pg.set_input_files('#file',{'name':'x.csv','mimeType':'text/csv','buffer':b'a,b\n1,2\n'});await pg.wait_for_timeout(400)
        print('BAD FILE after good: weather block visible =',await vis('#wx'))
        print('JS errors:',errs)
        await b.close()
asyncio.run(main())

def finish():
    text = "\n".join(_lines) + "\n"
    if "--update" in sys.argv:
        EXPECTED.write_text(text)
        builtins.print(f"\nsnapshot saved to {EXPECTED}")
        return
    if not EXPECTED.exists():
        sys.exit("No snapshot yet; run once with --update after reviewing the output above.")
    diff = list(difflib.unified_diff(EXPECTED.read_text().splitlines(), text.splitlines(), "expected", "actual", lineterm=""))
    if diff:
        builtins.print("\nFAIL: output differs from the snapshot\n" + "\n".join(diff))
        sys.exit(1)
    builtins.print("\nPASS: matches the saved snapshot")


finish()
