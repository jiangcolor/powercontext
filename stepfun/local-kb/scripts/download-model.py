"""Download public model files; verify published LFS hashes before local inference."""
import argparse, concurrent.futures, hashlib, json, pathlib, urllib.request
p=argparse.ArgumentParser();p.add_argument('--mirror',default='https://huggingface.co');a=p.parse_args()
revision='751bff37182d3f1213fa05d7196b954e230abad9'
root=pathlib.Path(__file__).resolve().parents[1];out=root/'public/models/Xenova/all-MiniLM-L6-v2'
files={'onnx/model_fp16.onnx':'2cdb5e58291813b6d6e248ed69010100246821a367fa17b1b81ae9483744533d','onnx/model.onnx':'759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e','onnx/model_quantized.onnx':'afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1',**dict.fromkeys(['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt'])}
def get(item):
 name,expected=item;dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True)
 if not dest.exists():
  url=f'{a.mirror.rstrip("/")}/Xenova/all-MiniLM-L6-v2/resolve/{revision}/{name}'
  temp=dest.with_suffix(dest.suffix+'.download');urllib.request.urlretrieve(url,temp);temp.replace(dest)
 digest=hashlib.sha256(dest.read_bytes()).hexdigest()
 if expected and digest!=expected:raise RuntimeError(f'Hash mismatch: {name}')
 return {'file':name,'bytes':dest.stat().st_size,'sha256':digest}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:result=list(ex.map(get,files.items()))
report={'model':'Xenova/all-MiniLM-L6-v2','revision':revision,'downloadSource':a.mirror,'files':result,'compressionRatioInt8':next(r['bytes'] for r in result if r['file']=='onnx/model.onnx')/next(r['bytes'] for r in result if r['file']=='onnx/model_quantized.onnx'),'compressionRatioFp16':next(r['bytes'] for r in result if r['file']=='onnx/model.onnx')/next(r['bytes'] for r in result if r['file']=='onnx/model_fp16.onnx')}
shared=sum(r['bytes'] for r in result if not r['file'].endswith('.onnx'))
report['sharedTokenizerAndConfigBytes']=shared
report['totalBytesByPrecision']={label:shared+next(r['bytes'] for r in result if r['file']==file) for label,file in [('fp32','onnx/model.onnx'),('int8','onnx/model_quantized.onnx'),('fp16','onnx/model_fp16.onnx')]}
report['totalCompressionRatioInt8']=report['totalBytesByPrecision']['fp32']/report['totalBytesByPrecision']['int8']
report['totalCompressionRatioFp16']=report['totalBytesByPrecision']['fp32']/report['totalBytesByPrecision']['fp16']
(root/'evidence/model-files.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
