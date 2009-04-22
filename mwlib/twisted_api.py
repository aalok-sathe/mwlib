#! /usr/bin/env python

# Copyright (c) 2007-2009 PediaPress GmbH
# See README.txt for additional licensing information.

"""client for mediawiki's api.php using twisted"""

import os
import sys
import urllib
import urlparse
import pprint
from mwlib.utils import fsescape
from mwlib.nshandling import nshandler 

from twisted.python import failure, log
from twisted.web import client
from twisted.internet import reactor, defer

try:
    import json
except ImportError:
    import simplejson as json
        
def merge_data(dst, src):
    orig = dst
    
    args = (dst, src)
    
    todo = [(dst, src)]
    while todo:
        dst, src = todo.pop()
        assert type(dst)==type(src), "cannot merge %r with %r" % (type(dst), type(src))
        
        if isinstance(dst, list):
            dst.extend(src)
        elif isinstance(dst, dict):
            for k, v in src.items():
                if k in dst:
                    
                    #assert isinstance(dst[k], (dict,list)), "wrong type %r" % (dict(k=k, v=v, d=dst[k]),)
                    
                    todo.append((dst[k], v))
                else:
                    dst[k] = v
        else:
            assert dst==src
    
def guess_api_urls(url):
    """
    @param url: URL of a MediaWiki article
    @type url: str
    
    @returns: APIHelper instance or None if it couldn't be guessed
    @rtype: @{APIHelper}
    """
    
    try:
        scheme, netloc, path, params, query, fragment = urlparse.urlparse(url)
    except ValueError:
        return []
    
    if not (scheme and netloc):
        return []
    

    path_prefix = ''
    if '/wiki/' in path:
        path_prefix = path[:path.find('/wiki/')]
    elif '/w/' in path:
        path_prefix = path[:path.find('/w/')]
    
    prefix = '%s://%s%s' % (scheme, netloc, path_prefix)

    retval = []
    for path in ('/w/', '/wiki/', '/'):
        base_url = '%s%sapi.php' % (prefix, path)
        retval.append(base_url)
    return retval


class mwapi(object):
    api_result_limit = 500 # 5000 for bots
    api_request_limit = 20 # at most 50 titles at once

    max_connections = 5
    
    def __init__(self, baseurl):
        self.baseurl = baseurl
        self._todo = []
        self.num_running = 0
        self.qccount = 0
        
        
    def idle(self):
        return self.num_running < self.max_connections

    def _fetch(self, url):
        errors = []
        d = defer.Deferred()
        
        def done(val):
            if isinstance(val, failure.Failure):
                errors.append(val)
                if len(errors)<2:
                    print "retrying: could not fetch %r" % (url,)
                    client.getPage(url).addCallbacks(done, done)
                else:
                    print "error: could not fetch %r" % (url,)
                    d.callback(val)
            else:
                d.callback(val)
            
                
        client.getPage(url).addCallbacks(done, done)
        return d
    
    def _maybe_fetch(self):
        def decref(res):
            self.num_running -= 1
            reactor.callLater(0.0, self._maybe_fetch)
            return res
        
        while self.num_running<self.max_connections and self._todo:
            url, d = self._todo.pop()
            self.num_running += 1
            # print url
            self._fetch(url).addCallbacks(decref, decref).addCallback(json.loads).chainDeferred(d)
            
    def _request(self, **kwargs):
        args = {'format': 'json'}
        args.update(**kwargs)
        for k, v in args.items():
            if isinstance(v, unicode):
                args[k] = v.encode('utf-8')
        q = urllib.urlencode(args)
        q = q.replace('%3A', ':') # fix for wrong quoting of url for images
        q = q.replace('%7C', '|') # fix for wrong quoting of API queries (relevant for redirects)

        url = "%s?%s" % (self.baseurl, q)
        #print "url:", url
        
        def decode(data):
            return json.loads(data)

        d=defer.Deferred()
        self._todo.append((url, d))
        reactor.callLater(0.0, self._maybe_fetch)
        return d
        
    def do_request(self, **kwargs):
        retval = {}
        
        def got_result(data):
            error = data.get("error")
            if error:
                print "error:", error.keys()
                return failure.Failure(RuntimeError(error.get("info", "")))

            merge_data(retval, data["query"])
            
            qc = data.get("query-continue", {}).values()
            
            if qc:
                self.qccount += 1
                
                #print "query-continuel:", qc, kwargs
                kw = kwargs.copy()
                for d in qc:
                    for k,v in d.items(): # dict of len(1)
                        kw[str(k)] = v
                return self._request(**kw).addCallback(got_result)
            return retval
        
        return self._request(**kwargs).addCallback(got_result)

    def get_siteinfo(self):
        return self.do_request(action="query", meta="siteinfo", siprop="general|namespaces|namespacealiases|magicwords|interwikimap")

    def _update_kwargs(self, kwargs, titles, revids):
        assert titles or kwargs
        
        if titles:
            kwargs["titles"] = "|".join(titles)
        if revids:
            kwargs["revids"] = "|".join([str(x) for x in revids])
        
    def fetch_used(self, titles=None, revids=None):
        kwargs = dict(prop="revisions|templates|images",
                      rvprop='ids',
                      redirects=1,
                      imlimit=self.api_result_limit,
                      tllimit=self.api_result_limit)

        self._update_kwargs(kwargs, titles, revids)
        return self.do_request(action="query", **kwargs)
        
    def fetch_pages(self, titles=None, revids=None):        
        kwargs = dict(prop="revisions",
                      rvprop='ids|content',
                      redirects=1,
                      imlimit=self.api_result_limit,
                      tllimit=self.api_result_limit)

        self._update_kwargs(kwargs, titles, revids)
        return self.do_request(action="query", **kwargs)

    def fetch_imageinfo(self, titles):

        kwargs = dict(prop="imageinfo",
                      iiprop="url",
                      iiurlwidth=800)
        self._update_kwargs(kwargs, titles, [])
        return self.do_request(action="query", **kwargs)
    
    def get_edits(self, title, revision, rvlimit=500):
        kwargs = {
            'titles': title,
            'redirects': 1,
            'prop': 'revisions',
            'rvprop': 'ids|user|flags|comment|size',
            'rvlimit': rvlimit,
            'rvdir': 'older',
        }
        if revision is not None:
            kwargs['rvstartid'] = revision

        return self.do_request(action="query", **kwargs)
        
    def get_imageinfo(self, titles):
        kwargs = dict(prop="imageinfo",
                      iiprop="user|comment|url|sha1|metadata|templates",
                      titles="|".join(titles))
        return self.do_request(action="query", **kwargs)
        


class fsoutput(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        assert not os.path.exists(self.path)
        os.makedirs(os.path.join(self.path, "images"))
        self.revfile = open(os.path.join(self.path, "revisions-1.txt"), "wb")
        self.revfile.write("\n -*- mode: wikipedia -*-\n")
        self.seen = set()
        self.imgcount = 0
        
    def get_imagepath(self, title):
        p = os.path.join(self.path, "images", "%s" % (fsescape(title),))
        self.imgcount+=1
        return p
        
    def dump_json(self, **kw):
        for k, v in kw.items():
            p = os.path.join(self.path, k+".json")
            json.dump(v, open(p, "wb"), indent=4)
            
                
    def write_siteinfo(self, siteinfo):
        self.dump_json(siteinfo=siteinfo)
        
    def write_pages(self, data):
        pages = data.get("pages", {}).values()
        for p in pages:
            
            title = p.get("title")
            ns = p.get("ns")
            revisions = p.get("revisions")
            
            if revisions is None:
                print "bad:", p
                continue

            tmp = []
            for x in revisions:
                x = x.copy()
                x["*"] = len(x["*"])
                tmp.append(x)
            
            for r in revisions:
                revid = r["revid"]
                txt = r["*"]
                if revid not in self.seen:
                    # assert title not in self.seen
                    self.seen.add(revid)
                    rev = dict(title=title, ns=ns, revid=revid)

                    header = "\n --page-- %s\n" % json.dumps(rev)
                    self.revfile.write(header)
                    self.revfile.write(txt.encode("utf-8"))
                # else:    
                #     print "fsoutput: skipping duplicate:", dict(revid=revid, title=title)

    def write_edits(self, edits):
        self.dump_json(edits=edits)

    def write_redirects(self, redirects):
        self.dump_json(redirects=redirects)
        
                        
def splitblocks(lst, limit):
    res = []
    start = 0
    while start<len(lst):
        res.append(lst[start:start+limit])
        start+=limit
    return res

def getblock(lst, limit):
    r = lst[-limit:]
    del lst[-limit:]
    return r


class fetcher(object):
    def __init__(self, api, fsout, pages):
        self.api = api
        self.fsout = fsout

        self.redirects = {}
        
        self.count_total = 0
        self.count_done = 0

        self.title2latest = {}
    
        self.edits = []
        self.pages_todo = []
        self.revids_todo = []
        self.imageinfo_todo = []
        
        self.scheduled = set()

        
        self._refcall(lambda:self.api.get_siteinfo().addCallback(self._cb_siteinfo))
        titles, revids = self._split_titles_revids(pages)
        

        limit = self.api.api_request_limit
        dl = []

        def fetch_used(name, lst):            
            for bl in splitblocks(lst, limit):
                kw = {name:bl}
                dl.append(self._refcall(lambda: self.api.fetch_used(**kw).addCallback(self._cb_used)))

        
        fetch_used("titles", titles)
        fetch_used("revids", revids)
        
        self._refcall(lambda: defer.DeferredList(dl).addCallbacks(self._cb_finish_used, self._cb_finish_used))
        
            
        self.report()
        self.dispatch()

    def _split_titles_revids(self, pages):
        titles = set()
        revids = set()        
           
        for p in pages:
            if p[1] is not None:
                revids.add(p[1])
            else:
                titles.add(p[0])
                
        titles = list(titles)
        titles.sort()

        revids = list(revids)
        revids.sort()
        return titles, revids

    def _cb_finish_used(self, data):
        for title, rev in self.title2latest.items():
             self._refcall(lambda: self.api.get_edits(title, rev).addCallback(self._got_edits))
        self.title2latest = {}
        
    def _cb_siteinfo(self, siteinfo):
        self.fsout.write_siteinfo(siteinfo)
        
    def report(self):
        isatty = getattr(sys.stdout, "isatty", None)
        if isatty and isatty():
            sys.stdout.write("\x1b[K")
            qc = self.api.qccount
            done = self.count_done+qc
            total = self.count_total+qc
            
            limit = self.api.api_request_limit
            jt = self.count_total+len(self.pages_todo)//limit+len(self.revids_todo)//limit
            jt += len(self.title2latest)
            
            sys.stdout.write("%s/%s/%s jobs -- %s/%s running" % (self.count_done, self.count_total, jt, self.api.num_running, self.api.max_connections))
            sys.stdout.write("\r")
            
    def _got_edits(self, data):
        edits = data.get("pages").values()
        self.edits.extend(edits)
        
    def _got_pages(self, data):
        self.fsout.write_pages(data)
        return data

    def _extract_attribute(self, lst, attr):
        res = []
        for x in lst:
            t = x.get(attr)
            if t:
                res.append(t)
        
        return res
    def _extract_title(self, lst):
        return self._extract_attribute(lst, "title")

    def _update_redirects(self, lst):
        for x in lst:
            t = x.get("to")
            f = x.get("from")
            if t and f:
                self.redirects[f]=t
                
    def _cb_used(self, used):
        self._update_redirects(used.get("redirects", []))        
        
        pages = used.get("pages", {}).values()
        
        revids = set()
        for p in pages:
            tmp = self._extract_attribute(p.get("revisions", []), "revid")
            if tmp:
                latest = max(tmp)
                title = p.get("title", None)
                old = self.title2latest.get(title, 0)
                self.title2latest[title] = max(old, latest)    
                
            revids.update(tmp)
        
        templates = set()
        images = set()
        for p in pages:
            images.update(self._extract_title(p.get("images", [])))
            templates.update(self._extract_title(p.get("templates", [])))

        for i in images:
            if i not in self.scheduled:
                self.imageinfo_todo.append(i)
                self.scheduled.add(i)
                
        for r in revids:
            if r not in self.scheduled:
                self.revids_todo.append(r)
                self.scheduled.add(r)
                
        for t in templates:
            if t not in self.scheduled:
                self.pages_todo.append(t)
                self.scheduled.add(t)

        
    def _cb_imageinfo(self, data):
        # print "data:", data
        infos = data.get("pages", {}).values()
        # print infos[0]
        
        for i in infos:
            title = i.get("title")
            
            ii = i.get("imageinfo", [])
            if not ii:
                continue
            ii = ii[0]
            thumburl = ii.get("thumburl", None)
            # FIXME limit number of parallel downloads
            if thumburl:
                self._refcall(lambda: client.downloadPage(str(thumburl), self.fsout.get_imagepath(title)))
                
        # print "imageinfo:", infos
        
        
    
    
    def dispatch(self):
        limit = self.api.api_request_limit

        def doit(name, lst):
            while lst and self.api.idle():
                bl = getblock(lst, limit)
                self.scheduled.update(bl)
                kw = {name:bl}
                self._refcall(lambda: self.api.fetch_pages(**kw).addCallback(self._got_pages))

        while self.imageinfo_todo and self.api.idle():
            bl = getblock(self.imageinfo_todo, limit)
            self.scheduled.update(bl)
            self._refcall(lambda: self.api.fetch_imageinfo(titles=bl).addCallback(self._cb_imageinfo))
            
        doit("revids", self.revids_todo)
        doit("titles", self.pages_todo)
        

        self.report()
        
        if self.count_done==self.count_total:
            self.finish()
            print
            reactor.stop()

    def finish(self):
        self.fsout.write_edits(self.edits)
        self.fsout.write_redirects(self.redirects)
        
    def _refcall(self, fun):
        self._incref()
        try:
            d=fun()
            assert isinstance(d, defer.Deferred), "got %r" % (d,)
        except:
            print "function failed"
            raise
            assert 0, "internal error"
        return d.addCallbacks(self._decref, self._decref)
        
    def _incref(self):
        self.count_total += 1
        self.report()
        
    def _decref(self, val):
        self.count_done += 1
        reactor.callLater(0.0, self.dispatch)
        if isinstance(val, failure.Failure):
            log.err(val)
            
        
def done(data):
    print "done", json.dumps(data, indent=4)
        

    
def doit(pages):
    api = mwapi("http://en.wikipedia.org/w/api.php")
    api.api_request_limit = 10

    # api.fetch_imageinfo(titles=["File:DSC00996.JPG", "File:MacedonEmpire.jpg"])
    # return
    # api.fetch_used([p[0] for p in pages]).addCallback(done)
    # return

    
    fs = fsoutput("tmp")

    
    f=fetcher(api, fs, pages)
    
    
      
    
def main():
    metabook = json.load(open("metabook.json"))
    pages  = [(x["title"], None)  for x in metabook["items"]]
    # pages = [("___user___:___schmir  __", None)] #, ("Mainz", None)]
    
    # log.startLogging(sys.stdout)
    reactor.callLater(0.0, doit, pages)
    reactor.run()
    
if __name__=="__main__":
    main()
    