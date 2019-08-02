# -*- coding: utf-8 -*-

from .base import Base
import denite.util
import subprocess
import tempfile
import re
import heapq
import platform;

class Source(Base):
    def __init__(self, vim):
        super().__init__(vim)
        self.name = 'go_import'
        self.kind = Kind(vim)
        self.persist_actions = []
        self.pkg_caches = []
        self.cache_key = self.name

    def on_init(self, context):
        # context['is_volatile'] = True
        # context['is_interactive'] = True
        pass

    def refresh_pkgs(self):
        try:
            output = subprocess.run(['gopkgs'], stdout=subprocess.PIPE, check=True)
            return output.stdout.decode('utf-8').splitlines()
        except subprocess.CalledProcessError as err:
            denite.util.error(self.vim, "command returned invalid response: " + str(err))
            return []

    def gather_candidates(self, context):
        return [{'word': x,} for x in self.refresh_pkgs()]

    def gather_candidates_interactive(self, context):
        if len(self.pkg_caches) == 0 or context["is_redraw"] == True:
            self.pkg_caches = self.refresh_pkgs()
            SetCandidates(self.cache_key, self.pkg_caches)

        rows = uniteMatch(self.cache_key, context["input"], 20, "")

        return [{'word': x,} for x in rows]

class Kind(object):
    def __init__(self, vim):
        self.vim = vim
        self.name = 'go_import'
        self.default_action ='import'
        self.persist_actions = ['preview']
        self.redraw_actions = []

        self._last_preview = {}

    def debug(self, expr):
        denite.util.debug(self.vim, expr)

    def get_action_names(self):
        return ['default'] + [x.replace('action_', '') for x in dir(self)
                if x.find('action_') == 0]

        #  xxx
    def action_import(self, context):
        for target in context['targets']:
            self._import(target['word'])

    def action_godoc(self, context):
        self.vim.call('go#doc#Open', 'new', 'split', context['targets'][0]['word'])

    def action_preview(self, context):
        pass

    def _import(self, name, local_name = ''):
        self.vim.call('go#import#SwitchImport', 1, local_name, name, '')


_escape = dict((c , "\\" + c) for c in ['^','$','.','{','}','(',')','[',']','\\','/','+'])

def filename_score(reprog, path, slash):
    # get filename via reverse find to improve performance
    slashPos = path.rfind(slash)
    filename = path[slashPos + 1:] if slashPos != -1 else path

    result = reprog.search(filename)
    if result:
        score = result.start() * 2
        score = score + result.end() - result.start() + 1
        score = score + ( len(filename) + 1 ) / 100.0
        score = score + ( len(path) + 1 ) / 1000.0
        return 1000.0 / score

    return 0

def path_score(reprog, line):
    result = reprog.search(line)
    if result:
        score = result.end() - result.start() + 1
        score = score + ( len(line) + 1 ) / 100.0
        return 1000.0 / score

    return 0

def dir_score(reprog, line):
    result = reprog.search(os.path.dirname(line))
    if result:
        score = result.end() - result.start() + 1
        score = score + ( len(line) + 1 ) / 100.0
        return 1000.0 / score

    return 0

def contain_upper(kw):
    prog = re.compile('[A-Z]+')
    return prog.search(kw)

def is_search_lower(kw):
    return False if contain_upper(kw) else True

def get_regex_prog(kw, isregex, islower):
    searchkw = kw.lower() if islower else kw

    regex = ''
    # Escape all of the characters as necessary
    escaped = [_escape.get(c, c) for c in searchkw]

    if isregex:
        if len(searchkw) > 1:
            regex = ''.join([c + "[^" + c + "]*" for c in escaped[:-1]])
        regex += escaped[-1]
    else:
        regex = ''.join(escaped)

    return re.compile(regex)

def Match(opts, rows, islower):
    res = []

    slash = '/' if platform.system() != "Windows" else '\\'

    for row in rows:
        line = row.lower() if islower else row
        scoreTotal = 0.0
        for kw, prog, mode in opts:
            score = 0.0

            if mode == 'filename-only':
                score = filename_score(prog, line, slash)
            elif mode == 'dir':
                score = dir_score(prog, line)
            else:
                score = path_score(prog, line)

            if score == 0:
                scoreTotal = 0
                break
            else:
                scoreTotal+=score

        if scoreTotal != 0:
            res.append((scoreTotal, row))

    return res

def GetFilterRows(rowsWithScore):
    rez = []
    rez.extend([line for score, line in rowsWithScore])
    return rez

def Sort(rowsWithScore, limit):
    rez = []
    rez.extend([line for score, line in heapq.nlargest(limit, rowsWithScore) if score != 0])
    return rez

candidates = {}
def SetCandidates(key, items):
    candidates[key] = items
    clearCache(key)

def loadCandidates(key, path):
    items = []
    with open(path,'r') as f:
        items = f.read().splitlines()

    setCandidates(key, items)

def LoadCandidates():
    key = vim.eval('s:key')
    path = vim.eval('s:path')

    loadCandidates(key, path)

candidatesCache = {}
resultCache = {}
def clearCache(key):
    candidatesCache[key] = {}
    resultCache[key] = {}

def getCacheKey(key, inputs):
    return key + "@" + inputs

def setCandidatesToCache(key, inputs, items):
    cache = candidatesCache.get(key, {})
    cache[inputs] = items

def getCandidatesFromCache(key, inputs):
    cache = candidatesCache.get(key, {})
    return cache.get(inputs, [])

def setResultToCache(key, inputs, items):
    cache = resultCache.get(key, {})
    cache[inputs] = items

def getResultFromCache(key, inputs):
    cache = resultCache.get(key, {})
    return cache.get(inputs, [])

def existCache(key, inputs):
    if key not in resultCache:
        return False

    if inputs not in resultCache[key]:
        return False

    return True

def getCandidates(key, inputs):
    if len(inputs) <= 1:
        return candidates.get(key, [])

    cacheInputs = inputs[:-1]
    if existCache(key, cacheInputs):
        return getCandidatesFromCache(key, cacheInputs)

    return candidates.get(key, [])

def uniteMatch(key, inputs, limit, mmode):
    isregex = True
    smartcase = True

    if existCache(key, inputs):
        return getResultFromCache(key, inputs)

    items = getCandidates(key, inputs)

    rows = items
    rowsFilter = items

    kwsAndDirs = inputs.split(';')
    strKws = kwsAndDirs[0] if len(kwsAndDirs) > 0 else ""
    strDir = kwsAndDirs[1] if len(kwsAndDirs) > 1 else ""

    islower = is_search_lower(inputs)

    opts = [(kw, get_regex_prog(kw, isregex, islower), mmode) for kw in strKws.split() if kw != ""]

    if strDir != "":
        opts.append((strDir, get_regex_prog(strDir, isregex, islower), 'dir'))

    if len(opts) > 0:
        rowsWithScore = Match(opts, rows, islower)
        rowsFilter = GetFilterRows(rowsWithScore)
        rows = Sort(rowsWithScore, limit)

        setCandidatesToCache(key, inputs, rowsFilter)
        setResultToCache(key, inputs, rows)

    if len(rows) > limit:
        rows = rows[:limit]

    return rows

def ClearCache(key):
    clearCache(key)
