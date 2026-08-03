
# # # ==========================================
# # # app.py - 瀹屾暣鐗?+ Agent浜屾楠岃瘉
# # # ==========================================
# # import json
# # import re
# # import os
# # import difflib
# # import base64
# # import shutil
# # from io import BytesIO
# # from fastapi import FastAPI, UploadFile, File, Request
# # from fastapi.responses import HTMLResponse
# # import fitz
# # import requests
# # from mineru import MinerU

# # app = FastAPI()

# # MINERU_API_TOKEN = "<REDACTED_TOKEN>"
# # DEEPSEEK_API_KEY = "<REDACTED_API_KEY>"
# # QWEN_API_KEY = "<REDACTED_API_KEY>"
# # UPLOAD_DIR = "uploads"
# # os.makedirs(UPLOAD_DIR, exist_ok=True)

# # COLORS = {
# #     'modified': (1, 0.85, 0),
# #     'deleted': (1, 0.3, 0.3),
# #     'added': (0.3, 0.8, 0.3),
# #     'signature': (0.3, 0.5, 1),
# #     'extra': (0.6, 0.3, 0.8),
# # }

# # # ==================== MinerU ====================

# # def find_layout_json(root_dir: str) -> str:
# #     for root, _, files in os.walk(root_dir):
# #         if "layout.json" in files:
# #             return os.path.join(root, "layout.json")
# #     return ""

# # def call_mineru(pdf_path: str) -> dict:
# #     temp_dir = "./temp_mineru_output"
# #     os.makedirs(temp_dir, exist_ok=True)
# #     os.makedirs("output", exist_ok=True)
# #     try:
# #         client = MinerU(MINERU_API_TOKEN)
# #         result = client.extract(pdf_path, model="vlm", ocr=True, formula=False, table=True, timeout=300)
# #         result.save_all(temp_dir)
# #         layout_path = find_layout_json(temp_dir)
# #         if layout_path:
# #             with open(layout_path, 'r', encoding='utf-8') as f:
# #                 layout = json.load(f)
# #             name = os.path.basename(pdf_path).replace('.pdf', '_layout.json')
# #             with open(os.path.join("output", name), 'w', encoding='utf-8') as f:
# #                 json.dump(layout, f, ensure_ascii=False, indent=2)
# #             return layout
# #         return {}
# #     finally:
# #         if os.path.exists(temp_dir):
# #             shutil.rmtree(temp_dir)

# # # ==================== Pipeline ====================

# # def extract_text(block: dict) -> str:
# #     texts = []
# #     if 'text' in block:
# #         t = block['text']
# #         texts.append(t if isinstance(t, str) else ' '.join(str(x) for x in t))
# #     for line in block.get('lines', []):
# #         for span in line.get('spans', []):
# #             if span.get('content'): texts.append(span['content'])
# #             if span.get('html'): texts.append(re.sub(r'<[^>]+>', ' ', span['html']))
# #     for sub in block.get('blocks', []): texts.append(extract_text(sub))
# #     return ' '.join(str(t) for t in texts).strip()

# # def flatten_layout(layout: dict) -> list:
# #     seen = set()
# #     blocks = []
# #     for page in layout.get('pdf_info', []):
# #         page_no = page.get('page_idx', 0)
# #         for key in ['para_blocks', 'preproc_blocks']:
# #             for block in page.get(key, []):
# #                 btype, bbox = block.get('type', 'text'), block.get('bbox', [0,0,0,0])
# #                 if btype == 'list' and 'blocks' in block:
# #                     for sub in block['blocks']:
# #                         text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
# #                         if text and (page_no, tuple(sb), text[:100]) not in seen:
# #                             seen.add((page_no, tuple(sb), text[:100]))
# #                             blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
# #                     continue
# #                 if btype == 'table' and 'blocks' in block:
# #                     for sub in block['blocks']:
# #                         text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
# #                         if text and (page_no, tuple(sb), text[:100]) not in seen:
# #                             seen.add((page_no, tuple(sb), text[:100]))
# #                             blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':'table_'+sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
# #                     continue
# #                 text = extract_text(block).strip()
# #                 if text and (page_no, tuple(bbox), text[:100]) not in seen:
# #                     seen.add((page_no, tuple(bbox), text[:100]))
# #                     blocks.append({'page':page_no,'y':bbox[1] if len(bbox)>=2 else 0,'type':btype,'text':text,'bbox':bbox,'_raw':block})
# #     blocks.sort(key=lambda x: (x['page'], x['y']))
# #     return blocks

# # def normalize(text: str) -> str:
# #     return re.sub(r'\s+','',text).replace('_','').replace('路','-').replace('鈥?,'-').replace('锛?,'(').replace('锛?,')').replace('锛?,':').replace('锛?,',').replace('銆?,'.').replace('锛?,';').lower()

# # def compare_blocks(before: list, after: list) -> dict:
# #     if not before or not after: return {'modified':[],'deleted':[],'added':[],'has_diff':False}
# #     bn, an = [normalize(b['text']) for b in before], [normalize(a['text']) for a in after]
# #     m = difflib.SequenceMatcher(None, bn, an)
# #     mod, dl, ad = [], [], []
# #     for tag,i1,i2,j1,j2 in m.get_opcodes():
# #         if tag=='equal': continue
# #         elif tag=='delete':
# #             for i in range(i1,i2): dl.append(before[i])
# #         elif tag=='insert':
# #             for j in range(j1,j2): ad.append(after[j])
# #         elif tag=='replace':
# #             for k in range(min(i2-i1,j2-j1)):
# #                 if bn[i1+k]!=an[j1+k]: mod.append({'old_text':before[i1+k]['text'],'new_text':after[j1+k]['text'],'old_bbox':before[i1+k]['bbox'],'new_bbox':after[j1+k]['bbox'],'page':before[i1+k]['page']})
# #             for i in range(i1+min(i2-i1,j2-j1),i2): dl.append(before[i])
# #             for j in range(j1+min(i2-i1,j2-j1),j2): ad.append(after[j])
# #     return {'modified':mod,'deleted':dl,'added':ad,'has_diff':len(mod)+len(dl)+len(ad)>0}

# # def find_signature_region(before_blocks: list, after_blocks: list) -> dict:
# #     table_idx = None
# #     for i,b in enumerate(before_blocks):
# #         if 'table' in b.get('type',''): table_idx=i; break
# #     if table_idx is None: return None
# #     ab, aa = None, None
# #     for i in range(table_idx-1,-1,-1):
# #         if 'table' not in before_blocks[i].get('type',''): ab=before_blocks[i]['text'][:30]; break
# #     for i in range(table_idx+1,len(before_blocks)):
# #         if 'table' not in before_blocks[i].get('type',''): aa=before_blocks[i]['text'][:30]; break
# #     if not ab or not aa: return None
# #     bboxes=[]
# #     for i in range(table_idx,len(before_blocks)):
# #         if 'table' in before_blocks[i].get('type',''): bboxes.append(before_blocks[i]['bbox'])
# #         else: break
# #     bm=[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]
# #     si,ei=None,None
# #     for i,b in enumerate(after_blocks):
# #         sb=difflib.SequenceMatcher(None,b['text'][:30],ab).ratio()
# #         sa=difflib.SequenceMatcher(None,b['text'][:30],aa).ratio()
# #         if sb>0.6 and si is None: si=i+1
# #         if sa>0.6 and si is not None: ei=i; break
# #     if si is None or ei is None or si>ei: return None
# #     region=after_blocks[si:ei]
# #     if not region: return None
# #     am=[min(b['bbox'][0]for b in region),min(b['bbox'][1]for b in region),max(b['bbox'][2]for b in region),max(b['bbox'][3]for b in region)]
# #     return {'page_before':before_blocks[table_idx]['page'],'page_after':region[0]['page'],'before_bbox':bm,'after_bbox':am,'before_table_start':table_idx,'before_table_end':table_idx+len(bboxes),'sig_start':si,'sig_end':ei,'before_table_blocks':before_blocks[table_idx:table_idx+len(bboxes)],'after_region_blocks':region}

# # def extract_table_fields(before_table_blocks: list) -> list:
# #     fields = []
# #     for block in before_table_blocks:
# #         for line in block.get('_raw',{}).get('lines',[]):
# #             for span in line.get('spans',[]):
# #                 html = span.get('html','')
# #                 if html:
# #                     td = re.sub(r'<[^>]+>',' ',html); td = re.sub(r'\s+',' ',td).strip()
# #                     for p in td.split(':'):
# #                         p=p.strip()
# #                         if p and not re.match(r'^\d',p): fields.append(p)
# #     return fields

# # def call_deepseek(prompt: str) -> str:
# #     try:
# #         resp = requests.post("https://api.deepseek.com/v1/chat/completions",
# #             headers={"Authorization":f"Bearer {DEEPSEEK_API_KEY}","Content-Type":"application/json"},
# #             json={"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],"temperature":0,"max_tokens":200},timeout=30)
# #         return resp.json()["choices"][0]["message"]["content"]
# #     except: return '{"filled":false}'

# # def check_signature_by_agent(before_table_blocks: list, after_region_blocks: list) -> bool:
# #     fields = extract_table_fields(before_table_blocks)
# #     if not fields: return False
# #     after_text = ' '.join(b['text'] for b in after_region_blocks)
# #     prompt = f"""鍒ゆ柇绛剧讲鍖哄煙瀛楁鏄惁宸插～鍐欍€傚瓧娈碉細{json.dumps(fields,ensure_ascii=False)}銆傚唴瀹癸細{after_text}銆傚彧杩斿洖JSON锛歿{"filled":true/false,"empty_fields":[],"summary":""}}"""
# #     try:
# #         content = call_deepseek(prompt).strip()
# #         if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
# #         return not json.loads(content).get('filled',True)
# #     except: return False

# # def find_extra_content(before_blocks: list, after_blocks: list) -> dict:
# #     if not before_blocks or not after_blocks: return None
# #     anchor = before_blocks[-1]['text'][:40]
# #     si = None
# #     for i,b in enumerate(after_blocks):
# #         if difflib.SequenceMatcher(None,b['text'][:40],anchor).ratio()>0.6: si=i+1; break
# #     if si is None or si>=len(after_blocks): return None
# #     extra = after_blocks[si:]
# #     if not extra: return None
# #     bboxes = [b['bbox'] for b in extra]
# #     return {'page':extra[0]['page'],'merged_bbox':[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]}

# # # ==================== Agent 浜屾楠岃瘉 ====================

# # def verify_diff_with_qwen(pdf_before: str, pdf_after: str, diff: dict) -> bool:
# #     """鐢ㄥ崈闂甐L瀵规瘮涓ゅ紶鎴浘锛屽垽鏂唴瀹规槸鍚︿竴鑷达紙蹇界暐鐩栫珷/绛惧悕锛?""
# #     try:
# #         doc_b = fitz.open(pdf_before)
# #         doc_a = fitz.open(pdf_after)
# #         page = diff['page']
        
# #         def capture(doc, bbox):
# #             rect = fitz.Rect(*bbox)
# #             rect = fitz.Rect(
# #                 max(0, rect[0]-15), max(0, rect[1]-15),
# #                 rect[2]+15, rect[3]+15
# #             )
# #             pix = doc[page].get_pixmap(clip=rect, matrix=fitz.Matrix(2, 2))
# #             return base64.b64encode(pix.tobytes("png")).decode()
        
# #         img_old = capture(doc_b, diff['old_bbox'])
# #         img_new = capture(doc_a, diff['new_bbox'])
# #         doc_b.close(); doc_a.close()
        
# #         prompt = """璇峰姣旇繖涓ゅ紶鏂囨。灞€閮ㄦ埅鍥俱€?
# # 宸﹀浘 = 鐩栫珷鍓嶏紝鍙冲浘 = 鐩栫珷鍚庛€?

# # 鍒ゆ柇鏍囧噯锛?
# # - 鍥剧墖涓唴瀹瑰彲鑳借鐩栦簡绔狅紝闇€瑕佷綘蹇界暐鎺夌洊绔犻儴鍒嗙殑棰滆壊锛屾枃瀛椼€?
# # - 濡傛灉涓ゅ紶鍥剧墖鐨勯潪鐩栫珷鏂囧瓧鍐呭锛堟潯娆俱€佹暟瀛椼€佹棩鏈熴€侀噾棰濈瓑锛夊畬鍏ㄤ竴鑷达紝鍙槸澶氫簡鐩栫珷/绛惧悕/鏍煎紡鍙樺寲 鈫?鏃犲樊寮?
# # - 濡傛灉鏂囧瓧鍐呭鏈夊彉鍖栵紙鏁板瓧涓嶅悓銆佹棩鏈熶笉鍚屻€佸瀛楀皯瀛楃瓑锛?鈫?鏈夊樊寮?

# # 鍙繑鍥濲SON锛歿"has_diff": true/false}"""
        
# #         resp = requests.post(
# #             "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
# #             headers={"Authorization": f"Bearer {QWEN_API_KEY}", "Content-Type": "application/json"},
# #             json={
# #                 "model": "qwen3.5-omni-plus-2026-03-15",
# #                 "messages": [{
# #                     "role": "user",
# #                     "content": [
# #                         {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_old}"}},
# #                         {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_new}"}},
# #                         {"type": "text", "text": prompt}
# #                     ]
# #                 }]
# #             },
# #             timeout=30
# #         )
# #         result = resp.json()
        
# #         # 鎵撳嵃 token 娑堣€?
# #         usage = result.get('usage', {})
# #         print(f"      馃搳 Token: prompt={usage.get('prompt_tokens')}, "
# #               f"completion={usage.get('completion_tokens')}, "
# #               f"total={usage.get('total_tokens')}")
        
# #         content = result['choices'][0]['message']['content']
# #         if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
# #         return json.loads(content).get('has_diff', True)
# #     except Exception as e:
# #         print(f"   鈿狅笍 鍗冮棶楠岃瘉澶辫触: {e}")
# #         return True
    


# # def run_pipeline(layout_before: dict, layout_after: dict, pdf_before: str, pdf_after: str) -> list:
# #     bb = flatten_layout(layout_before)
# #     ab = flatten_layout(layout_after)
# #     print(f"   鐩栫珷鍓? {len(bb)} 鍧? 鐩栫珷鍚? {len(ab)} 鍧?)
    
# #     sig = find_signature_region(bb, ab)
# #     shd = False
# #     if sig:
# #         print(f"   绛剧讲鍖哄煙: 鐩栫珷鍓嶇{sig['page_before']+1}椤? 鐩栫珷鍚庣{sig['page_after']+1}椤?)
# #         shd = check_signature_by_agent(sig['before_table_blocks'], sig['after_region_blocks'])
# #         bbody = bb[:sig['before_table_start']] + bb[sig['before_table_end']:]
# #         abody = ab[:sig['sig_start']] + ab[sig['sig_end']:]
# #     else:
# #         bbody, abody = bb, ab
    
# #     diff = compare_blocks(bbody, abody)
# #     print(f"   鍊欓€変慨鏀? {len(diff['modified'])} 澶?)
    
# #     extra = find_extra_content(bbody, abody)
    
# #     diffs = []
# #     for i, m in enumerate(diff['modified']):
# #         if not (m.get('old_bbox') and len(m['old_bbox'])==4 and m.get('new_bbox') and len(m['new_bbox'])==4):
# #             continue
# #         # Agent 浜屾楠岃瘉
# #         print(f"   馃 Agent楠岃瘉 [{i+1}/{len(diff['modified'])}]...")
# #         real = verify_diff_with_qwen(pdf_before, pdf_after, m)
# #         if real:
# #             print(f"      馃毃 纭宸紓: {m['old_text'][:40]}")
# #             diffs.append({'type':'modified','page':m['page'],'old_text':m['old_text'],'new_text':m['new_text'],'old_bbox':m['old_bbox'],'new_bbox':m['new_bbox']})
# #         else:
# #             print(f"      鉁?杩囨护璇姤: {m['old_text'][:40]}")
    
# #     for d in diff['deleted']:
# #         if d.get('bbox') and len(d['bbox'])==4:
# #             diffs.append({'type':'deleted','page':d['page'],'text':d['text'],'bbox':d['bbox']})
# #     for a in diff['added']:
# #         if a.get('bbox') and len(a['bbox'])==4:
# #             diffs.append({'type':'added','page':a['page'],'text':a['text'],'bbox':a['bbox']})
# #     if sig and shd:
# #         diffs.append({'type':'signature','page':sig['page_after'],'before_bbox':sig['before_bbox'],'after_bbox':sig['after_bbox']})
# #     if extra:
# #         diffs.append({'type':'extra','page':extra['page'],'bbox':extra['merged_bbox']})
    
# #     print(f"   鏈€缁堝樊寮? {len(diffs)} 澶?)
# #     return diffs

# # def pdf_to_highlighted_images(pdf_path: str, diffs: list, side: str) -> list:
# #     doc = fitz.open(pdf_path)
# #     for diff in diffs:
# #         page = diff.get('page', 0)
# #         if page >= len(doc): continue
# #         bbox = None
# #         if diff['type'] == 'modified':
# #             bbox = diff.get('new_bbox') if side == 'after' else diff.get('old_bbox')
# #         elif diff['type'] == 'deleted' and side == 'before':
# #             bbox = diff.get('bbox')
# #         elif diff['type'] == 'added' and side == 'after':
# #             bbox = diff.get('bbox')
# #         elif diff['type'] == 'signature':
# #             bbox = diff.get('after_bbox') if side == 'after' else diff.get('before_bbox')
# #         elif diff['type'] == 'extra' and side == 'after':
# #             bbox = diff.get('bbox')
# #         if not bbox or len(bbox) != 4: continue
# #         rect = fitz.Rect(*bbox)
# #         color = COLORS.get(diff['type'], (1, 0.85, 0))
# #         doc[page].draw_rect(rect, color=color, fill=color, width=2, fill_opacity=0.35)
# #     images = []
# #     for page in doc:
# #         pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
# #         images.append(base64.b64encode(pix.tobytes("png")).decode())
# #     doc.close()
# #     return images

# # # ==================== API ====================

# # @app.get("/", response_class=HTMLResponse)
# # async def index():
# #     with open("templates/index.html", 'r', encoding='utf-8') as f:
# #         return f.read()

# # @app.post("/compare")
# # async def compare(request: Request):
# #     form = await request.form()
# #     fb = form.get("file_before"); fa = form.get("file_after")
# #     pb = os.path.join(UPLOAD_DIR, "before.pdf"); pa = os.path.join(UPLOAD_DIR, "after.pdf")
# #     with open(pb,'wb') as f: f.write(await fb.read())
# #     with open(pa,'wb') as f: f.write(await fa.read())
# #     print("馃搫 MinerU...")
# #     lb = call_mineru(pb); la = call_mineru(pa)
# #     print("馃攳 Pipeline + Agent楠岃瘉...")
# #     diffs = run_pipeline(lb, la, pb, pa)
# #     print("馃柤锔?鐢熸垚楂樹寒鍥剧墖...")
# #     return {
# #         "diffs": diffs,
# #         "before_images": pdf_to_highlighted_images(pb, diffs, 'before'),
# #         "after_images": pdf_to_highlighted_images(pa, diffs, 'after')
# #     }

# # if __name__ == "__main__":
# #     import uvicorn
# #     uvicorn.run(app, host="0.0.0.0", port=8000)


# # ==========================================
# # app.py - 瀹屾暣鐗?+ Agent楠岃瘉 + 閲嶅彔妫€娴?
# # ==========================================
# import json
# import re
# import os
# import difflib
# import base64
# import shutil
# from io import BytesIO
# from fastapi import FastAPI, UploadFile, File, Request
# from fastapi.responses import HTMLResponse
# import fitz
# import requests
# from mineru import MinerU

# app = FastAPI()

# MINERU_API_TOKEN = "<REDACTED_TOKEN>"
# DEEPSEEK_API_KEY = "<REDACTED_API_KEY>"
# QWEN_API_KEY = "<REDACTED_API_KEY>"
# UPLOAD_DIR = "uploads"
# os.makedirs(UPLOAD_DIR, exist_ok=True)

# COLORS = {
#     'modified': (1, 0.85, 0),
#     'deleted': (1, 0.3, 0.3),
#     'added': (0.3, 0.8, 0.3),
#     'signature': (0.3, 0.5, 1),
#     'extra': (0.6, 0.3, 0.8),
# }

# # ==================== MinerU ====================

# def find_layout_json(root_dir: str) -> str:
#     for root, _, files in os.walk(root_dir):
#         if "layout.json" in files:
#             return os.path.join(root, "layout.json")
#     return ""

# def call_mineru(pdf_path: str) -> dict:
#     temp_dir = "./temp_mineru_output"
#     os.makedirs(temp_dir, exist_ok=True)
#     os.makedirs("output", exist_ok=True)
#     try:
#         client = MinerU(MINERU_API_TOKEN)
#         result = client.extract(pdf_path, model="vlm", ocr=True, formula=False, table=True, timeout=300)
#         result.save_all(temp_dir)
#         layout_path = find_layout_json(temp_dir)
#         if layout_path:
#             with open(layout_path, 'r', encoding='utf-8') as f:
#                 layout = json.load(f)
#             name = os.path.basename(pdf_path).replace('.pdf', '_layout.json')
#             with open(os.path.join("output", name), 'w', encoding='utf-8') as f:
#                 json.dump(layout, f, ensure_ascii=False, indent=2)
#             return layout
#         return {}
#     finally:
#         if os.path.exists(temp_dir):
#             shutil.rmtree(temp_dir)

# # ==================== Pipeline ====================

# def extract_text(block: dict) -> str:
#     texts = []
#     if 'text' in block:
#         t = block['text']
#         texts.append(t if isinstance(t, str) else ' '.join(str(x) for x in t))
#     for line in block.get('lines', []):
#         for span in line.get('spans', []):
#             if span.get('content'): texts.append(span['content'])
#             if span.get('html'): texts.append(re.sub(r'<[^>]+>', ' ', span['html']))
#     for sub in block.get('blocks', []): texts.append(extract_text(sub))
#     return ' '.join(str(t) for t in texts).strip()

# def flatten_layout(layout: dict) -> list:
#     seen = set()
#     blocks = []
#     for page in layout.get('pdf_info', []):
#         page_no = page.get('page_idx', 0)
#         for key in ['para_blocks', 'preproc_blocks']:
#             for block in page.get(key, []):
#                 btype, bbox = block.get('type', 'text'), block.get('bbox', [0,0,0,0])
#                 if btype == 'list' and 'blocks' in block:
#                     for sub in block['blocks']:
#                         text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
#                         if text and (page_no, tuple(sb), text[:100]) not in seen:
#                             seen.add((page_no, tuple(sb), text[:100]))
#                             blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
#                     continue
#                 if btype == 'table' and 'blocks' in block:
#                     for sub in block['blocks']:
#                         text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
#                         if text and (page_no, tuple(sb), text[:100]) not in seen:
#                             seen.add((page_no, tuple(sb), text[:100]))
#                             blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':'table_'+sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
#                     continue
#                 text = extract_text(block).strip()
#                 if text and (page_no, tuple(bbox), text[:100]) not in seen:
#                     seen.add((page_no, tuple(bbox), text[:100]))
#                     blocks.append({'page':page_no,'y':bbox[1] if len(bbox)>=2 else 0,'type':btype,'text':text,'bbox':bbox,'_raw':block})
#     blocks.sort(key=lambda x: (x['page'], x['y']))
#     return blocks

# def normalize(text: str) -> str:
#     return re.sub(r'\s+','',text).replace('_','').replace('路','-').replace('鈥?,'-').replace('锛?,'(').replace('锛?,')').replace('锛?,':').replace('锛?,',').replace('銆?,'.').replace('锛?,';').lower()

# def compare_blocks(before: list, after: list) -> dict:
#     if not before or not after: return {'modified':[],'deleted':[],'added':[],'has_diff':False}
#     bn, an = [normalize(b['text']) for b in before], [normalize(a['text']) for a in after]
#     m = difflib.SequenceMatcher(None, bn, an)
#     mod, dl, ad = [], [], []
#     for tag,i1,i2,j1,j2 in m.get_opcodes():
#         if tag=='equal': continue
#         elif tag=='delete':
#             for i in range(i1,i2): dl.append(before[i])
#         elif tag=='insert':
#             for j in range(j1,j2): ad.append(after[j])
#         elif tag=='replace':
#             for k in range(min(i2-i1,j2-j1)):
#                 if bn[i1+k]!=an[j1+k]: mod.append({'old_text':before[i1+k]['text'],'new_text':after[j1+k]['text'],'old_bbox':before[i1+k]['bbox'],'new_bbox':after[j1+k]['bbox'],'page':before[i1+k]['page']})
#             for i in range(i1+min(i2-i1,j2-j1),i2): dl.append(before[i])
#             for j in range(j1+min(i2-i1,j2-j1),j2): ad.append(after[j])
#     return {'modified':mod,'deleted':dl,'added':ad,'has_diff':len(mod)+len(dl)+len(ad)>0}

# def find_signature_region(before_blocks: list, after_blocks: list) -> dict:
#     table_idx = None
#     for i,b in enumerate(before_blocks):
#         if 'table' in b.get('type',''): table_idx=i; break
#     if table_idx is None: return None
#     ab, aa = None, None
#     for i in range(table_idx-1,-1,-1):
#         if 'table' not in before_blocks[i].get('type',''): ab=before_blocks[i]['text'][:30]; break
#     for i in range(table_idx+1,len(before_blocks)):
#         if 'table' not in before_blocks[i].get('type',''): aa=before_blocks[i]['text'][:30]; break
#     if not ab or not aa: return None
#     bboxes=[]
#     for i in range(table_idx,len(before_blocks)):
#         if 'table' in before_blocks[i].get('type',''): bboxes.append(before_blocks[i]['bbox'])
#         else: break
#     bm=[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]
#     si,ei=None,None
#     for i,b in enumerate(after_blocks):
#         sb=difflib.SequenceMatcher(None,b['text'][:30],ab).ratio()
#         sa=difflib.SequenceMatcher(None,b['text'][:30],aa).ratio()
#         if sb>0.6 and si is None: si=i+1
#         if sa>0.6 and si is not None: ei=i; break
#     if si is None or ei is None or si>ei: return None
#     region=after_blocks[si:ei]
#     if not region: return None
#     am=[min(b['bbox'][0]for b in region),min(b['bbox'][1]for b in region),max(b['bbox'][2]for b in region),max(b['bbox'][3]for b in region)]
#     return {'page_before':before_blocks[table_idx]['page'],'page_after':region[0]['page'],'before_bbox':bm,'after_bbox':am,'before_table_start':table_idx,'before_table_end':table_idx+len(bboxes),'sig_start':si,'sig_end':ei,'before_table_blocks':before_blocks[table_idx:table_idx+len(bboxes)],'after_region_blocks':region}

# def extract_table_fields(before_table_blocks: list) -> list:
#     fields = []
#     for block in before_table_blocks:
#         for line in block.get('_raw',{}).get('lines',[]):
#             for span in line.get('spans',[]):
#                 html = span.get('html','')
#                 if html:
#                     td = re.sub(r'<[^>]+>',' ',html); td = re.sub(r'\s+',' ',td).strip()
#                     for p in td.split(':'):
#                         p=p.strip()
#                         if p and not re.match(r'^\d',p): fields.append(p)
#     return fields

# def call_deepseek(prompt: str) -> str:
#     try:
#         resp = requests.post("https://api.deepseek.com/v1/chat/completions",
#             headers={"Authorization":f"Bearer {DEEPSEEK_API_KEY}","Content-Type":"application/json"},
#             json={"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],"temperature":0,"max_tokens":200},timeout=30)
#         return resp.json()["choices"][0]["message"]["content"]
#     except: return '{"filled":false}'

# def check_signature_by_agent(before_table_blocks: list, after_region_blocks: list) -> bool:
#     fields = extract_table_fields(before_table_blocks)
#     if not fields: return False
#     after_text = ' '.join(b['text'] for b in after_region_blocks)
#     prompt = f"""鍒ゆ柇绛剧讲鍖哄煙瀛楁鏄惁宸插～鍐欍€傚瓧娈碉細{json.dumps(fields,ensure_ascii=False)}銆傚唴瀹癸細{after_text}銆傚彧杩斿洖JSON锛歿{"filled":true/false,"empty_fields":[],"summary":""}}"""
#     try:
#         content = call_deepseek(prompt).strip()
#         if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
#         return not json.loads(content).get('filled',True)
#     except: return False

# def find_extra_content(before_blocks: list, after_blocks: list) -> dict:
#     if not before_blocks or not after_blocks: return None
#     anchor = before_blocks[-1]['text'][:40]
#     si = None
#     for i,b in enumerate(after_blocks):
#         if difflib.SequenceMatcher(None,b['text'][:40],anchor).ratio()>0.6: si=i+1; break
#     if si is None or si>=len(after_blocks): return None
#     extra = after_blocks[si:]
#     if not extra: return None
#     bboxes = [b['bbox'] for b in extra]
#     return {'page':extra[0]['page'],'merged_bbox':[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]}

# def is_bbox_overlap(bbox1, bbox2):
#     if not bbox1 or not bbox2 or len(bbox1)!=4 or len(bbox2)!=4: return False
#     return not (bbox1[2]<bbox2[0] or bbox2[2]<bbox1[0] or bbox1[3]<bbox2[1] or bbox2[3]<bbox1[1])

# # ==================== Agent 楠岃瘉 ====================

# def verify_diff_with_qwen(pdf_before: str, pdf_after: str, diff: dict) -> bool:
#     try:
#         doc_b = fitz.open(pdf_before); doc_a = fitz.open(pdf_after)
#         page = diff['page']
#         def capture(doc, bbox):
#             rect = fitz.Rect(*bbox)
#             rect = fitz.Rect(max(0,rect[0]-15),max(0,rect[1]-15),rect[2]+15,rect[3]+15)
#             pix = doc[page].get_pixmap(clip=rect, matrix=fitz.Matrix(2,2))
#             return base64.b64encode(pix.tobytes("png")).decode()
#         img_old = capture(doc_b, diff['old_bbox']); img_new = capture(doc_a, diff['new_bbox'])
#         doc_b.close(); doc_a.close()
#         resp = requests.post(
#             "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
#             headers={"Authorization":f"Bearer {QWEN_API_KEY}","Content-Type":"application/json"},
#             json={"model":"qwen3.5-omni-plus-2026-03-15","messages":[{"role":"user","content":[
#                 {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_old}"}},
#                 {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_new}"}},
#                 {"type":"text","text":"瀵规瘮涓ゅ紶鏂囨。灞€閮ㄦ埅鍥撅紝鍒ゆ柇鍐呭鏄惁瀹炶川涓€鑷淬€傚拷鐣ョ洊绔?绛惧悕/鏍煎紡鍙樺寲銆傚彧杩斿洖JSON锛歿\"has_diff\":true/false}"}
#             ]}],"max_tokens":50},timeout=30)
#         result = resp.json()
#         usage = result.get('usage',{})
#         print(f"      馃搳 Token: total={usage.get('total_tokens')}")
#         content = result['choices'][0]['message']['content']
#         if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
#         return json.loads(content).get('has_diff', True)
#     except Exception as e:
#         print(f"   鈿狅笍 鍗冮棶楠岃瘉澶辫触: {e}")
#         return True

# # ==================== 涓绘祦绋?====================

# def run_pipeline(layout_before: dict, layout_after: dict, pdf_before: str, pdf_after: str) -> list:
#     bb = flatten_layout(layout_before); ab = flatten_layout(layout_after)
#     print(f"   鐩栫珷鍓? {len(bb)} 鍧? 鐩栫珷鍚? {len(ab)} 鍧?)
    
#     sig = find_signature_region(bb, ab)
#     shd = False
#     if sig:
#         print(f"   绛剧讲鍖哄煙: 鐩栫珷鍓嶇{sig['page_before']+1}椤? 鐩栫珷鍚庣{sig['page_after']+1}椤?)
#         shd = check_signature_by_agent(sig['before_table_blocks'], sig['after_region_blocks'])
#         bbody = bb[:sig['before_table_start']] + bb[sig['before_table_end']:]
#         abody = ab[:sig['sig_start']] + ab[sig['sig_end']:]
#     else:
#         bbody, abody = bb, ab
    
#     diff = compare_blocks(bbody, abody)
#     print(f"   鍊欓€変慨鏀? {len(diff['modified'])} 澶?)
    
#     extra = find_extra_content(bbody, abody)
#     extra_bbox = extra['merged_bbox'] if extra else None
    
#     diffs = []
#     for i, m in enumerate(diff['modified']):
#         if not (m.get('old_bbox') and len(m['old_bbox'])==4 and m.get('new_bbox') and len(m['new_bbox'])==4): continue
#         print(f"   馃 Agent楠岃瘉 [{i+1}/{len(diff['modified'])}]...")
#         real = verify_diff_with_qwen(pdf_before, pdf_after, m)
#         if real:
#             print(f"      馃毃 纭宸紓: {m['old_text'][:40]}")
#             diffs.append({'type':'modified','page':m['page'],'old_text':m['old_text'],'new_text':m['new_text'],'old_bbox':m['old_bbox'],'new_bbox':m['new_bbox']})
#         else:
#             print(f"      鉁?杩囨护璇姤: {m['old_text'][:40]}")
    
#     for d in diff['deleted']:
#         if d.get('bbox') and len(d['bbox'])==4:
#             if extra_bbox and is_bbox_overlap(d['bbox'], extra_bbox): continue
#             diffs.append({'type':'deleted','page':d['page'],'text':d['text'],'bbox':d['bbox']})
#     for a in diff['added']:
#         if a.get('bbox') and len(a['bbox'])==4:
#             if extra_bbox and is_bbox_overlap(a['bbox'], extra_bbox): continue
#             diffs.append({'type':'added','page':a['page'],'text':a['text'],'bbox':a['bbox']})
#     if sig and shd:
#         diffs.append({'type':'signature','page':sig['page_after'],'before_bbox':sig['before_bbox'],'after_bbox':sig['after_bbox']})
#     if extra:
#         diffs.append({'type':'extra','page':extra['page'],'bbox':extra['merged_bbox']})
    
#     print(f"   鏈€缁堝樊寮? {len(diffs)} 澶?)
#     return diffs

# def pdf_to_highlighted_images(pdf_path: str, diffs: list, side: str) -> list:
#     doc = fitz.open(pdf_path)
#     for diff in diffs:
#         page = diff.get('page', 0)
#         if page >= len(doc): continue
#         bbox = None
#         if diff['type']=='modified': bbox = diff.get('new_bbox') if side=='after' else diff.get('old_bbox')
#         elif diff['type']=='deleted' and side=='before': bbox = diff.get('bbox')
#         elif diff['type']=='added' and side=='after': bbox = diff.get('bbox')
#         elif diff['type']=='signature': bbox = diff.get('after_bbox') if side=='after' else diff.get('before_bbox')
#         elif diff['type']=='extra' and side=='after': bbox = diff.get('bbox')
#         if not bbox or len(bbox)!=4: continue
#         color = COLORS.get(diff['type'], (1,0.85,0))
#         doc[page].draw_rect(fitz.Rect(*bbox), color=color, fill=color, width=2, fill_opacity=0.35)
#     images = []
#     for page in doc:
#         pix = page.get_pixmap(matrix=fitz.Matrix(1.5,1.5))
#         images.append(base64.b64encode(pix.tobytes("png")).decode())
#     doc.close()
#     return images

# # ==================== API ====================

# @app.get("/", response_class=HTMLResponse)
# async def index():
#     with open("templates/index.html", 'r', encoding='utf-8') as f:
#         return f.read()

# @app.post("/compare")
# async def compare(request: Request):
#     form = await request.form()
#     fb = form.get("file_before"); fa = form.get("file_after")
#     pb = os.path.join(UPLOAD_DIR, "before.pdf"); pa = os.path.join(UPLOAD_DIR, "after.pdf")
#     with open(pb,'wb') as f: f.write(await fb.read())
#     with open(pa,'wb') as f: f.write(await fa.read())
#     print("馃搫 MinerU...")
#     lb = call_mineru(pb); la = call_mineru(pa)
#     print("馃攳 Pipeline + Agent...")
#     diffs = run_pipeline(lb, la, pb, pa)
#     print("馃柤锔?鐢熸垚鍥剧墖...")
#     return {
#         "diffs": diffs,
#         "before_images": pdf_to_highlighted_images(pb, diffs, 'before'),
#         "after_images": pdf_to_highlighted_images(pa, diffs, 'after')
#     }

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)
# ==========================================
# app.py - 鏂囨。瀵规瘮骞冲彴锛堣嚜寤篗inerU鏈嶅姟鍣級
# ==========================================
import json
import re
import os
import io
import zipfile
import difflib
import base64
import time
from io import BytesIO
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse
import fitz
import requests

app = FastAPI()

MINERU_URL = os.getenv("MINERU_URL", "http://10.89.1.235:7803/file_parse")
MINERU_MD_API_URL = os.getenv("MINERU_MD_API_URL", "http://10.89.1.235:8010")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

COLORS = {
    'modified': (1, 0.85, 0),
    'deleted': (1, 0.3, 0.3),
    'added': (0.3, 0.8, 0.3),
    'signature': (0.3, 0.5, 1),
    'extra': (0.6, 0.3, 0.8),
}

# ==================== MinerU锛堢粺涓€瑙ｆ瀽鎺ュ彛锛?====================

def call_mineru(pdf_path: str) -> dict:
    task_id = submit_mineru_parse_task(pdf_path)
    if not task_id:
        return {}
    result = wait_mineru_parse_done(task_id)
    if not result:
        return {}
    json_url = result.get("json_url")
    if not json_url:
        print(f"   鏈幏鍙栧埌 layout JSON 鍦板潃: task_id={task_id}")
        return {}
    try:
        resp = requests.get(json_url, timeout=120)
        resp.raise_for_status()
        layout = resp.json()
    except Exception as e:
        print(f"   璇诲彇 layout JSON 澶辫触: {e}")
        return {}

    if layout:
        os.makedirs("output", exist_ok=True)
        save_name = os.path.basename(pdf_path).replace('.pdf', '_layout.json')
        save_path = os.path.join("output", save_name)
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        print(f"   瑙ｆ瀽鎺ュ彛鑾峰彇鎴愬姛 -> {save_path}")
    return layout


def submit_mineru_parse_task(file_path: str) -> str:
    try:
        with open(file_path, 'rb') as f:
            resp = requests.post(
                f"{MINERU_MD_API_URL.rstrip('/')}/parse-md",
                files={"file": (os.path.basename(file_path), f, "application/pdf")},
                data={"user_id": "contract_compare"},
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("task_id", "")
        print(f"   鎻愪氦瑙ｆ瀽浠诲姟: {task_id}, status={data.get('status')}")
        return task_id
    except Exception as e:
        print(f"   鎻愪氦瑙ｆ瀽浠诲姟澶辫触: {e}")
        return ""


def wait_mineru_parse_done(task_id: str, timeout: int = 600, interval: int = 2) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        try:
            resp = requests.get(f"{MINERU_MD_API_URL.rstrip('/')}/parse-md/{task_id}", timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"   鏌ヨ瑙ｆ瀽浠诲姟澶辫触: {e}")
            time.sleep(interval)
            continue

        status = data.get("status")
        print(f"   瑙ｆ瀽浠诲姟鐘舵€? {task_id}, status={status}, progress={data.get('progress')}")
        if status == "done":
            return data
        if status == "failed":
            print(f"   瑙ｆ瀽浠诲姟澶辫触: {data.get('error')}")
            return {}
        time.sleep(interval)

    print(f"   瑙ｆ瀽浠诲姟瓒呮椂: {task_id}")
    return {}


def call_mineru_direct(pdf_path: str) -> dict:
    with open(pdf_path, 'rb') as f:
        files = [("files", (os.path.basename(pdf_path), f))]
        data = {
            "backend": "hybrid-auto-engine",
            "response_format_zip": True,
            "return_middle_json": True,
            "return_model_output": False,
            "return_content_list": False
        }
        resp = requests.post(MINERU_URL, files=files, data=data, timeout=600)

    if resp.status_code != 200:
        print(f"   鉂?MinerU 澶辫触: {resp.status_code}")
        return {}

    zip_data = io.BytesIO(resp.content)
    zf = zipfile.ZipFile(zip_data)

    layout = {}
    for name in zf.namelist():
        if name.endswith('middle.json'):
            layout = json.loads(zf.read(name).decode('utf-8'))
            break
    zf.close()

    if layout:
        save_name = os.path.basename(pdf_path).replace('.pdf', '_layout.json')
        save_path = os.path.join("output", save_name)
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        print(f"   鉁?鑾峰彇鎴愬姛 鈫?{save_path}")

    return layout

    zip_data = io.BytesIO(resp.content)
    zf = zipfile.ZipFile(zip_data)

    for name in zf.namelist():
        if name.endswith('middle.json'):
            content = zf.read(name).decode('utf-8')
            zf.close()
            layout = json.loads(content)
            print(f"   鉁?鑾峰彇鎴愬姛 ({len(layout.get('pdf_info',[]))} 椤?")
            return layout

    zf.close()
    return {}

# ==================== Pipeline ====================

def extract_text(block: dict) -> str:
    texts = []
    if 'text' in block:
        t = block['text']
        texts.append(t if isinstance(t, str) else ' '.join(str(x) for x in t))
    for line in block.get('lines', []):
        for span in line.get('spans', []):
            if span.get('content'): texts.append(span['content'])
            if span.get('html'): texts.append(re.sub(r'<[^>]+>', ' ', span['html']))
    for sub in block.get('blocks', []): texts.append(extract_text(sub))
    return ' '.join(str(t) for t in texts).strip()

def flatten_layout(layout: dict) -> list:
    seen = set()
    blocks = []
    for page in layout.get('pdf_info', []):
        page_no = page.get('page_idx', 0)
        for key in ['para_blocks', 'preproc_blocks']:
            for block in page.get(key, []):
                btype, bbox = block.get('type', 'text'), block.get('bbox', [0,0,0,0])
                if btype == 'list' and 'blocks' in block:
                    for sub in block['blocks']:
                        text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
                        if text and (page_no, tuple(sb), text[:100]) not in seen:
                            seen.add((page_no, tuple(sb), text[:100]))
                            blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
                    continue
                if btype == 'table' and 'blocks' in block:
                    for sub in block['blocks']:
                        text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
                        if text and (page_no, tuple(sb), text[:100]) not in seen:
                            seen.add((page_no, tuple(sb), text[:100]))
                            blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':'table_'+sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
                    continue
                text = extract_text(block).strip()
                if text and (page_no, tuple(bbox), text[:100]) not in seen:
                    seen.add((page_no, tuple(bbox), text[:100]))
                    blocks.append({'page':page_no,'y':bbox[1] if len(bbox)>=2 else 0,'type':btype,'text':text,'bbox':bbox,'_raw':block})
    blocks.sort(key=lambda x: (x['page'], x['y']))
    return blocks

def normalize(text: str) -> str:
    return re.sub(r'\s+','',text).replace('_','').replace('路','-').replace('鈥?,'-').replace('锛?,'(').replace('锛?,')').replace('锛?,':').replace('锛?,',').replace('銆?,'.').replace('锛?,';').lower()

def compare_blocks(before: list, after: list) -> dict:
    if not before or not after: 
        return {'modified':[],'deleted':[],'added':[],'has_diff':False}
    
    bn = [normalize(b['text']) for b in before]
    an = [normalize(a['text']) for a in after]
    matcher = difflib.SequenceMatcher(None, bn, an)
    
    modified, deleted, added = [], [], []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        
        elif tag == 'delete':
            for i in range(i1, i2):
                deleted.append(before[i])
        
        elif tag == 'insert':
            for j in range(j1, j2):
                added.append(after[j])
        
        elif tag == 'replace':
            # 鍏堝悎骞朵袱杈规墍鏈夊潡锛岀湅鏄惁涓€鑷?
            b_merged = normalize(''.join(b['text'] for b in before[i1:i2]))
            a_merged = normalize(''.join(a['text'] for a in after[j1:j2]))
            
            if b_merged == a_merged:
                # 鍚堝苟鍚庝竴鑷?鈫?娈佃惤鎷嗗垎宸紓锛岃烦杩?
                continue
            
            # 涓嶄竴鑷?鈫?閫愪釜瀵规瘮
            for k in range(min(i2-i1, j2-j1)):
                if bn[i1+k] != an[j1+k]:
                    modified.append({
                        'old_text': before[i1+k]['text'],
                        'new_text': after[j1+k]['text'],
                        'old_bbox': before[i1+k].get('bbox', []),
                        'new_bbox': after[j1+k].get('bbox', []),
                        'page': before[i1+k]['page']
                    })
            
            # 澶氫綑鐨?
            for i in range(i1 + min(i2-i1, j2-j1), i2):
                deleted.append(before[i])
            for j in range(j1 + min(i2-i1, j2-j1), j2):
                added.append(after[j])
    
    return {
        'modified': modified,
        'deleted': deleted,
        'added': added,
        'has_diff': len(modified)+len(deleted)+len(added) > 0
    }

def find_signature_region(before_blocks: list, after_blocks: list) -> dict:
    table_idx = None
    for i,b in enumerate(before_blocks):
        if 'table' in b.get('type',''): table_idx=i; break
    if table_idx is None: return None
    ab, aa = None, None
    for i in range(table_idx-1,-1,-1):
        if 'table' not in before_blocks[i].get('type',''): ab=before_blocks[i]['text'][:30]; break
    for i in range(table_idx+1,len(before_blocks)):
        if 'table' not in before_blocks[i].get('type',''): aa=before_blocks[i]['text'][:30]; break
    if not ab or not aa: return None
    bboxes=[]
    for i in range(table_idx,len(before_blocks)):
        if 'table' in before_blocks[i].get('type',''): bboxes.append(before_blocks[i]['bbox'])
        else: break
    bm=[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]
    si,ei=None,None
    for i,b in enumerate(after_blocks):
        sb=difflib.SequenceMatcher(None,b['text'][:30],ab).ratio()
        sa=difflib.SequenceMatcher(None,b['text'][:30],aa).ratio()
        if sb>0.6 and si is None: si=i+1
        if sa>0.6 and si is not None: ei=i; break
    if si is None or ei is None or si>ei: return None
    region=after_blocks[si:ei]
    if not region: return None
    am=[min(b['bbox'][0]for b in region),min(b['bbox'][1]for b in region),max(b['bbox'][2]for b in region),max(b['bbox'][3]for b in region)]
    return {'page_before':before_blocks[table_idx]['page'],'page_after':region[0]['page'],'before_bbox':bm,'after_bbox':am,'before_table_start':table_idx,'before_table_end':table_idx+len(bboxes),'sig_start':si,'sig_end':ei,'before_table_blocks':before_blocks[table_idx:table_idx+len(bboxes)],'after_region_blocks':region}

def extract_table_fields(before_table_blocks: list) -> list:
    fields = []
    for block in before_table_blocks:
        for line in block.get('_raw',{}).get('lines',[]):
            for span in line.get('spans',[]):
                html = span.get('html','')
                if html:
                    td = re.sub(r'<[^>]+>',' ',html); td = re.sub(r'\s+',' ',td).strip()
                    for p in td.split(':'):
                        p=p.strip()
                        if p and not re.match(r'^\d',p): fields.append(p)
    return fields

def call_deepseek(prompt: str) -> str:
    try:
        resp = requests.post("https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization":f"Bearer {DEEPSEEK_API_KEY}","Content-Type":"application/json"},
            json={"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],"temperature":0,"max_tokens":200},timeout=30)
        return resp.json()["choices"][0]["message"]["content"]
    except: return '{"filled":false}'

def check_signature_by_agent(before_table_blocks: list, after_region_blocks: list) -> bool:
    fields = extract_table_fields(before_table_blocks)
    if not fields: return False
    after_text = ' '.join(b['text'] for b in after_region_blocks)
    prompt = f"""鍒ゆ柇绛剧讲鍖哄煙瀛楁鏄惁宸插～鍐欍€傚瓧娈碉細{json.dumps(fields,ensure_ascii=False)}銆傚唴瀹癸細{after_text}銆傚彧杩斿洖JSON锛歿{"filled":true/false,"empty_fields":[],"summary":""}}"""
    try:
        content = call_deepseek(prompt).strip()
        if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
        return not json.loads(content).get('filled',True)
    except: return False

def find_extra_content(before_blocks: list, after_blocks: list) -> dict:
    if not before_blocks or not after_blocks: return None
    anchor = before_blocks[-1]['text'][:40]
    si = None
    for i,b in enumerate(after_blocks):
        if difflib.SequenceMatcher(None,b['text'][:40],anchor).ratio()>0.6: si=i+1; break
    if si is None or si>=len(after_blocks): return None
    extra = after_blocks[si:]
    if not extra: return None
    bboxes = [b['bbox'] for b in extra]
    return {'page':extra[0]['page'],'merged_bbox':[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]}

def is_bbox_overlap(bbox1, bbox2):
    if not bbox1 or not bbox2 or len(bbox1)!=4 or len(bbox2)!=4: return False
    return not (bbox1[2]<bbox2[0] or bbox2[2]<bbox1[0] or bbox1[3]<bbox2[1] or bbox2[3]<bbox1[1])

def verify_diff_with_qwen(pdf_before: str, pdf_after: str, diff: dict) -> bool:
    try:
        print(f"      old: {diff['old_text'][:60]}")
        print(f"      new: {diff['new_text'][:60]}")
        doc_b = fitz.open(pdf_before); doc_a = fitz.open(pdf_after)
        page = diff['page']
        def capture(doc, bbox):
            rect = fitz.Rect(*bbox)
            rect = fitz.Rect(max(0,rect[0]-15),max(0,rect[1]-15),rect[2]+15,rect[3]+15)
            pix = doc[page].get_pixmap(clip=rect, matrix=fitz.Matrix(2,2))
            return base64.b64encode(pix.tobytes("png")).decode()
        img_old = capture(doc_b, diff['old_bbox']); img_new = capture(doc_a, diff['new_bbox'])
        doc_b.close(); doc_a.close()
        resp = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization":f"Bearer {QWEN_API_KEY}","Content-Type":"application/json"},
            json={"model":"qwen3.5-omni-plus-2026-03-15","messages":[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_old}"}},
                {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_new}"}},
                {"type":"text","text":"瀵规瘮涓ゅ紶鏂囨。灞€閮ㄦ埅鍥撅紝鍒ゆ柇鍐呭鏄惁瀹炶川涓€鑷淬€傚拷鐣ョ洊绔?绛惧悕/鏍煎紡鍙樺寲銆傚彧杩斿洖JSON锛歿\"has_diff\":true/false}"}
            ]}],"max_tokens":50},timeout=30)
        content = resp.json()['choices'][0]['message']['content']
        if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
        return json.loads(content).get('has_diff', True)
    except Exception as e:
        print(f"   鈿狅笍 鍗冮棶楠岃瘉澶辫触: {e}")
        return True

def run_pipeline(layout_before: dict, layout_after: dict, pdf_before: str, pdf_after: str) -> list:
    bb = flatten_layout(layout_before); ab = flatten_layout(layout_after)
    print(f"   鐩栫珷鍓? {len(bb)} 鍧? 鐩栫珷鍚? {len(ab)} 鍧?)
    sig = find_signature_region(bb, ab)
    shd = False
    if sig:
        print(f"   绛剧讲鍖哄煙: 鐩栫珷鍓嶇{sig['page_before']+1}椤? 鐩栫珷鍚庣{sig['page_after']+1}椤?)
        shd = check_signature_by_agent(sig['before_table_blocks'], sig['after_region_blocks'])
        bbody = bb[:sig['before_table_start']] + bb[sig['before_table_end']:]
        abody = ab[:sig['sig_start']] + ab[sig['sig_end']:]
    else:
        bbody, abody = bb, ab
    diff = compare_blocks(bbody, abody)
    print(f"   鍊欓€変慨鏀? {len(diff['modified'])} 澶?)
    extra = find_extra_content(bbody, abody)
    extra_bbox = extra['merged_bbox'] if extra else None
    diffs = []
    for i, m in enumerate(diff['modified']):
        if not (m.get('old_bbox') and len(m['old_bbox'])==4 and m.get('new_bbox') and len(m['new_bbox'])==4): continue
        print(f"   馃 Agent楠岃瘉 [{i+1}/{len(diff['modified'])}]...")
        if verify_diff_with_qwen(pdf_before, pdf_after, m):
            print(f"      馃毃 纭宸紓: {m['old_text'][:40]}")
            diffs.append({'type':'modified','page':m['page'],'old_text':m['old_text'],'new_text':m['new_text'],'old_bbox':m['old_bbox'],'new_bbox':m['new_bbox']})
        else:
            print(f"      鉁?杩囨护璇姤: {m['old_text'][:40]}")
    for d in diff['deleted']:
        if d.get('bbox') and len(d['bbox'])==4:
            if extra_bbox and is_bbox_overlap(d['bbox'], extra_bbox): continue
            diffs.append({'type':'deleted','page':d['page'],'text':d['text'],'bbox':d['bbox']})
    for a in diff['added']:
        if a.get('bbox') and len(a['bbox'])==4:
            if extra_bbox and is_bbox_overlap(a['bbox'], extra_bbox): continue
            diffs.append({'type':'added','page':a['page'],'text':a['text'],'bbox':a['bbox']})
    if sig and shd:
        diffs.append({'type':'signature','page':sig['page_after'],'before_bbox':sig['before_bbox'],'after_bbox':sig['after_bbox']})
    if extra:
        diffs.append({'type':'extra','page':extra['page'],'bbox':extra['merged_bbox']})
    print(f"   鏈€缁堝樊寮? {len(diffs)} 澶?)
    return diffs

def pdf_to_highlighted_images(pdf_path: str, diffs: list, side: str) -> list:
    doc = fitz.open(pdf_path)
    for diff in diffs:
        page = diff.get('page', 0)
        if page >= len(doc): continue
        bbox = None
        if diff['type']=='modified': bbox = diff.get('new_bbox') if side=='after' else diff.get('old_bbox')
        elif diff['type']=='deleted' and side=='before': bbox = diff.get('bbox')
        elif diff['type']=='added' and side=='after': bbox = diff.get('bbox')
        elif diff['type']=='signature': bbox = diff.get('after_bbox') if side=='after' else diff.get('before_bbox')
        elif diff['type']=='extra' and side=='after': bbox = diff.get('bbox')
        if not bbox or len(bbox)!=4: continue
        doc[page].draw_rect(fitz.Rect(*bbox), color=COLORS.get(diff['type'],(1,0.85,0)), fill=COLORS.get(diff['type'],(1,0.85,0)), width=2, fill_opacity=0.35)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5,1.5))
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return images

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html", 'r', encoding='utf-8') as f:
        return f.read()

@app.post("/compare")
async def compare(request: Request):
    form = await request.form()
    fb = form.get("file_before"); fa = form.get("file_after")
    pb = os.path.join(UPLOAD_DIR, "before.pdf"); pa = os.path.join(UPLOAD_DIR, "after.pdf")
    with open(pb,'wb') as f: f.write(await fb.read())
    with open(pa,'wb') as f: f.write(await fa.read())
    print("馃搫 MinerU 鑷缓鏈嶅姟鍣?..")
    lb = call_mineru(pb); la = call_mineru(pa)
    print("馃攳 Pipeline + Agent...")
    diffs = run_pipeline(lb, la, pb, pa)
    print("馃柤锔?鐢熸垚鍥剧墖...")
    return {"diffs": diffs, "before_images": pdf_to_highlighted_images(pb, diffs, 'before'), "after_images": pdf_to_highlighted_images(pa, diffs, 'after')}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

