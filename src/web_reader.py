"""受限网页资料读取：公网地址、DNS固定、跳转逐次检查；无登录/下载/脚本。"""
import html, http.client, ipaddress, socket, ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

class WebSafetyError(ValueError): pass

def public_endpoint(url):
    p=urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise WebSafetyError('仅允许无凭据HTTP(S)链接')
    # 显式 :0 不能折成默认端口（老写法 p.port or 80 会把 :0 变成 80，绕过端口白名单检查）
    if p.port == 0: raise WebSafetyError('禁止端口 0')
    port=p.port or (443 if p.scheme=='https' else 80)
    if port not in (80,443): raise WebSafetyError('禁止非标准端口')
    host=p.hostname.encode('idna').decode('ascii')
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(x[4][0] for x in addresses))
    if not ips: raise WebSafetyError('DNS无结果')
    for ip in ips:
        address=ipaddress.ip_address(ip)
        # is_global 对组播是 True（实测 224.0.0.1 / ff02::1），只看它会漏掉 224/4 与 ff00::/8，
        # 所以组播、保留地址显式挡；v4-mapped 的 IPv6 拆开按同样规则看。
        mapped=getattr(address,'ipv4_mapped',None)
        targets=[address]+([mapped] if mapped else [])
        if any((not a.is_global) or a.is_multicast or a.is_reserved for a in targets):
            raise WebSafetyError('禁止私网、本机、保留地址和混合DNS结果')
    return p,host,port,ips[0]

class TextOnly(HTMLParser):
    def __init__(self): super().__init__(); self.hidden=0; self.parts=[]
    def handle_starttag(self,t,a):
        if t in ('script','style','noscript','svg'): self.hidden+=1
        if t in ('p','div','br','h1','h2','h3','li'): self.parts.append('\n')
    def handle_endtag(self,t):
        if t in ('script','style','noscript','svg'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,d):
        if not self.hidden: self.parts.append(d)

def fetch_public_text(url,cfg):
    original=url
    for _ in range(4):
        p,host,port,ip=public_endpoint(url)
        cls=http.client.HTTPSConnection if p.scheme=='https' else http.client.HTTPConnection
        con=cls(host,port=port,timeout=cfg.get('timeout',10))
        # 固定此次DNS核验得到的IP；TLS仍校验原hostname，避免DNS重绑定。
        con._create_connection=lambda address,timeout=None,source_address=None: socket.create_connection((ip,port),timeout,source_address)
        try:
            path=p.path or '/'
            if p.query: path+='?'+p.query
            con.request('GET',path,headers={'User-Agent':'WechatBot-ReadOnly/1.0','Accept':'text/html,text/plain','Accept-Encoding':'identity'})
            res=con.getresponse()
            if res.status in (301,302,303,307,308):
                location=res.getheader('Location')
                if not location: raise WebSafetyError('无效跳转')
                url=urljoin(url,location); continue
            if res.status!=200: raise WebSafetyError('网页返回HTTP '+str(res.status))
            mime=(res.getheader('Content-Type') or '').lower()
            if not any(x in mime for x in ('text/html','text/plain','application/xhtml+xml')):
                raise WebSafetyError('不下载附件或非文本内容')
            if res.getheader('Content-Encoding') not in (None,'identity'):
                raise WebSafetyError('不处理压缩内容')
            limit=cfg.get('max_bytes',250000)
            data=res.read(limit+1)
            if len(data)>limit: raise WebSafetyError('网页超过读取上限')
            charset=res.headers.get_content_charset() or 'utf-8'
            try: text=data.decode(charset,errors='replace')
            except LookupError: text=data.decode('utf-8',errors='replace')
            if 'html' in mime:
                parser=TextOnly(); parser.feed(text); text=' '.join(parser.parts)
            return {'url':original,'final_url':url,'status':'read','untrusted_text':text[:cfg.get('max_chars',9000)]}
        finally: con.close()
    raise WebSafetyError('跳转次数超限')
