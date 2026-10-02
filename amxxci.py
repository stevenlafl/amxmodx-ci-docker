#!/usr/bin/env python3
"""AMX Mod X CI tools: compile and lint .sma plugins.

Usage:
  amxxci.py compile [options] [<dir|file.sma>...]
  amxxci.py lint [options] <dir|file.sma>...

compile (also run as compile.sh):
  No arguments: compile every *.sma in the current directory, always exit 0.
  Otherwise directories are searched recursively for .sma files, listed files
  are compiled as given, and include/ folders under the directories (or next
  to the files) become include paths after the stock includes and ./include.
  Arguments starting with - are passed to amxxpc; a custom -o keeps the old
  single-invocation behavior. Plugins compile in parallel (JOBS, default all
  CPUs) into compiled/<name>.amxx, only when the compiler reports no errors.
  Prints "N compiled, M failed" and exits 1 if anything failed.

lint (also run as lint.sh): see "amxxci.py lint --help".

Written for python3-minimal: no tempfile, shutil, queue or concurrent.futures.
"""
import argparse, collections, json, os, re, struct, subprocess, sys, threading, zlib

STOCK = os.environ.get('AMXX_INCLUDE', '/amxmodx/include')
AMXXPC = os.environ.get('AMXXPC', 'amxxpc')
ERROR_RE = re.compile(r'error \d+:')
MSG_RE = re.compile(r'^(.+?)\((\d+)(?: -- \d+)?\) : (warning|error|fatal error) (\d+): (.*)$')
INC_RE = re.compile(rb'^[ \t]*#include[ \t]*([<"])([^>"]+)[>"]', re.M)


# ---------------------------------------------------------------- helpers

def jobs_default():
    return int(os.environ.get('JOBS') or os.cpu_count() or 1)


def parallel(func, items, jobs):
    """Run func over items with up to `jobs` threads, results in input order."""
    items = list(items)
    results = [None] * len(items)
    lock = threading.Lock()
    nxt = [0]

    def worker():
        while True:
            with lock:
                i = nxt[0]
                nxt[0] += 1
            if i >= len(items):
                return
            results[i] = func(items[i])
    errors = []

    def guarded():
        try:
            worker()
        except BaseException as e:
            errors.append(e)
    threads = [threading.Thread(target=guarded) for _ in range(max(1, min(jobs, len(items))))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]
    return results


_tmp_lock = threading.Lock()
_tmp_count = [0]


def make_tempdir(prefix='amxxci.'):
    base = os.environ.get('TMPDIR', '/tmp')
    while True:
        with _tmp_lock:
            _tmp_count[0] += 1
            n = _tmp_count[0]
        path = os.path.join(base, '%s%d.%d' % (prefix, os.getpid(), n))
        try:
            os.mkdir(path, 0o700)
            return path
        except FileExistsError:
            continue


def move_file(src, dst):
    """os.replace, falling back to copy and delete across filesystems (like mv)."""
    try:
        os.replace(src, dst)
    except OSError:
        with open(src, 'rb') as i, open(dst + '.part', 'wb') as o:
            o.write(i.read())
        os.replace(dst + '.part', dst)
        os.unlink(src)


def remove_tree(path):
    if not os.path.isdir(path):
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            os.rmdir(os.path.join(root, d))
    os.rmdir(path)


def discover(paths):
    """Expand directories and files into (.sma files, include dirs found under them)."""
    files, incdirs = [], []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort()
                if os.path.basename(root) == 'include':
                    incdirs.append(root)
                files += [os.path.join(root, n) for n in sorted(names) if n.endswith('.sma')]
        else:
            files.append(p)
            inc = os.path.join(os.path.dirname(p), 'include')
            if os.path.isdir(inc):
                incdirs.append(inc)
    local = os.path.realpath('include')
    seen, uniq = set(), []
    for d in incdirs:
        r = os.path.realpath(d)
        if r not in seen and r != local:
            seen.add(r)
            uniq.append(d)
    return files, uniq


def run_amxxpc(args):
    r = subprocess.run([AMXXPC] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.stdout.decode(errors='replace')


def compile_to(src, out, incs, opts=()):
    """Compile src to out; ok only if the compiler printed no errors and wrote out."""
    log = run_amxxpc(['-i' + STOCK, '-iinclude'] + ['-i' + d for d in incs] + list(opts) + [src, '-o' + out])
    return not ERROR_RE.search(log) and os.path.exists(out), log


# ---------------------------------------------------------------- compile

def compile_one(src, incs, opts):
    tmp = make_tempdir()
    try:
        out = os.path.join(tmp, os.path.basename(src)[:-4] + '.amxx' if src.endswith('.sma') else os.path.basename(src) + '.amxx')
        ok, log = compile_to(src, out, incs, opts)
        if ok:
            os.makedirs('compiled', exist_ok=True)
            move_file(out, os.path.join('compiled', os.path.basename(out)))
        return ok, log
    finally:
        remove_tree(tmp)


def compile_many(files, incs, opts, jobs):
    results = parallel(lambda f: compile_one(f, incs, opts), files, jobs)
    failed = []
    for f, (ok, log) in zip(files, results):
        print('Compiling %s ...' % f)
        sys.stdout.write(log)
        print('')
        if not ok:
            failed.append(f)
    return failed


def cmd_compile(argv):
    os.makedirs('compiled', exist_ok=True)
    jobs = jobs_default()
    if not argv:
        files = sorted(n for n in os.listdir('.') if n.endswith('.sma'))
        compile_many(files, [], [], jobs)
        return 0
    if any(a.startswith('-o') for a in argv):
        # Original behavior: one amxxpc call, move whatever it produced
        sys.stdout.write(run_amxxpc(['-i' + STOCK, '-iinclude'] + argv))
        moved = 0
        for n in sorted(os.listdir('.')):
            if n.endswith('.amxx') and os.path.isfile(n):
                move_file(n, os.path.join('compiled', n))
                moved += 1
        return 0 if moved else 1
    opts = [a for a in argv if a.startswith('-')]
    files, incs = discover([a for a in argv if not a.startswith('-')])
    names = collections.Counter()
    for d in incs + (['include'] if os.path.isdir('include') else []):
        names.update(n for n in os.listdir(d) if n.endswith('.inc'))
    dupes = sorted(n for n, c in names.items() if c > 1)
    if dupes:
        print('Warning: include files found in more than one include folder: ' + ' '.join(dupes), file=sys.stderr)
    if not files:
        print('No .sma files found in: ' + ' '.join(argv), file=sys.stderr)
        return 1
    failed = compile_many(files, incs, opts, jobs)
    print('%d compiled, %d failed' % (len(files) - len(failed), len(failed)))
    for f in failed:
        print('  ' + f)
    return 1 if failed else 0


# ---------------------------------------------------------------- AMX images

def amx_image(path):
    d = open(path, 'rb').read()
    for i in range(d[6]):
        cellsize, disksize, _, _, offs = struct.unpack_from('<BIIII', d, 7 + 17 * i)
        if cellsize == 4:
            img = zlib.decompress(d[offs:offs + disksize])
            return img[:struct.unpack_from('<i', img, 0)[0]]
    raise ValueError('no 32-bit section in ' + path)


def amx_tables(img):
    defsize = struct.unpack_from('<h', img, 10)[0]
    cod, dat, hea = struct.unpack_from('<iii', img, 12)
    pub, nat, lib, pv, tag, nt = struct.unpack_from('<6i', img, 32)

    def names(a, b):
        out = []
        for e in range(a, b, defsize):
            o = struct.unpack_from('<i', img, e + 4)[0]
            out.append(img[o:img.index(b'\0', o)].decode(errors='replace'))
        return out
    # Load-time markers live in the tags table: ?rl_<lib> (#pragma reqlib),
    # ?f_<module> (force-load), ?rc_<class> (#pragma reqclass), ?d_<module> (default)
    return {'publics': names(pub, nat), 'natives': names(nat, lib), 'libraries': names(lib, pv),
            'pubvars': names(pv, tag), 'tags': names(tag, nt), 'code': img[cod:hea]}


def markers(t):
    return set(t['libraries']) | {n for n in t['tags'] if n.startswith('?')}


# ---------------------------------------------------------------- lint

LINT_HELP = """Usage: amxxci.py lint [options] <dir|file.sma>...

Paths work like compile. Checks:
  warnings      compiler warnings and errors per plugin, with deprecations,
                unreachable code and unused values called out
  includes      #include lines that can be removed: recompiles each plugin once
                per include with that line commented out (skip: --no-includes)
  requirements  libraries and modules each plugin needs at load time, and which
                plugin or module provides them; with --plugins-ini, checks that
                every enabled plugin's plugin libraries are provided by an
                enabled plugin
  natives       natives registered by a plugin that no linted plugin calls
  static        include names whose case differs from the file on disk, and
                files mixing CRLF and LF line endings

Options:
  --plugins-ini FILE     plugins.ini to check requirements against (repeatable)
  --no-includes          skip the include check
  --baseline FILE        compare per-plugin warning counts with FILE
  --write-baseline FILE  write per-plugin warning counts to FILE
  --strict               exit 1 on compile errors, warning regressions or
                         unresolved requirements
  -j, --jobs N           parallel compiles (default: JOBS or all CPUs)

On GitHub Actions, findings are also emitted as annotations and a markdown job
summary. Without --strict the exit code is always 0.
"""
CATEGORIES = {'233': 'deprecated', '225': 'unreachable code', '203': 'unused symbol',
              '204': 'assigned but never used', '213': 'tag mismatch', '217': 'loose indentation'}


def parse_messages(log):
    out = []
    for line in log.splitlines():
        m = MSG_RE.match(line.strip())
        if m:
            f, ln, kind, code, text = m.groups()
            out.append({'file': os.path.normpath(f), 'line': int(ln), 'kind': kind, 'code': code, 'text': text})
    return out


def stock_module_libraries():
    libs = set()
    for root, _, names in os.walk(STOCK):
        for n in names:
            if n.endswith('.inc'):
                txt = open(os.path.join(root, n), errors='replace').read()
                libs.update(re.findall(r'#pragma\s+(?:reqlib|library|loadlib|reqclass)\s+"?(\w+)', txt))
    return libs


def read_plugins_ini(path):
    enabled = []
    for line in open(path, errors='replace'):
        line = line.strip()
        if not line or line.startswith((';', '//', '#')):
            continue
        enabled.append(re.sub(r'\.amxx$', '', line.split()[0], flags=re.I))
    return enabled


class Report:
    def __init__(self):
        self.sections = collections.OrderedDict()
        self.annotations = []
        self.failures = []

    def add(self, section, line):
        self.sections.setdefault(section, []).append(line)

    def annotate(self, level, file, line, title, msg):
        self.annotations.append((level, file, line, title, msg))


def cmd_lint(argv):
    ap = argparse.ArgumentParser(prog='amxxci.py lint', add_help=False)
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--plugins-ini', action='append', default=[])
    ap.add_argument('--no-includes', action='store_true')
    ap.add_argument('--baseline')
    ap.add_argument('--write-baseline')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('-j', '--jobs', type=int, default=jobs_default())
    ap.add_argument('-h', '--help', action='store_true')
    a = ap.parse_args(argv)
    if a.help or not a.paths:
        print(LINT_HELP)
        return 0 if a.help else 2

    files, incdirs = discover(a.paths)
    files = [os.path.normpath(f) for f in files]
    if not files:
        print('No .sma files found in: ' + ' '.join(a.paths), file=sys.stderr)
        return 2
    names = {f: os.path.splitext(os.path.basename(f))[0] for f in files}
    rep = Report()
    work = make_tempdir('amxxlint.')
    try:
        # Each plugin compiles from its real path so messages point at real
        # files; its own folder goes last so quoted includes resolve the same
        # way for the variants compiled from temp copies below
        def base_job(f):
            return compile_to(f, os.path.join(work, names[f] + '.orig.amxx'), incdirs, ['-d0', '-i' + (os.path.dirname(f) or '.')])
        orig = dict(zip(files, parallel(base_job, files, a.jobs)))
        images = {f: amx_image(os.path.join(work, names[f] + '.orig.amxx')) for f in files if orig[f][0]}
        tables = {f: amx_tables(img) for f, img in images.items()}

        # Warnings and errors
        counts, seen = {}, set()
        for f in files:
            ok, log = orig[f]
            msgs = parse_messages(log)
            counts[names[f]] = dict(collections.Counter(m['code'] for m in msgs if m['kind'] == 'warning'))
            if not ok:
                rep.add('Compile errors', '%s: does not compile' % f)
                rep.failures.append('compile error: ' + f)
            for m in msgs:
                key = (m['file'], m['line'], m['code'], m['text'])
                if key in seen:
                    continue
                seen.add(key)
                cat = CATEGORIES.get(m['code'], m['kind'])
                level = 'warning' if m['kind'] == 'warning' else 'error'
                rep.add('Compiler %ss' % level,
                        '%s:%d: %s %s (%s): %s' % (m['file'], m['line'], m['kind'], m['code'], cat, m['text']))
                rep.annotate(level, m['file'], m['line'], '%s %s (%s)' % (m['kind'], m['code'], cat), m['text'])
        totals = collections.Counter()
        for c in counts.values():
            totals.update(c)
        if totals:
            rep.add('Warning totals', ', '.join('%s %s: %d' % (k, CATEGORIES.get(k, ''), v) for k, v in sorted(totals.items())))
        if a.baseline and os.path.exists(a.baseline):
            base = json.load(open(a.baseline))
            for p, c in sorted(counts.items()):
                for code, n in sorted(c.items()):
                    was = base.get(p, {}).get(code, 0)
                    if n > was:
                        rep.add('Warning regressions', '%s: warning %s %d -> %d' % (p, code, was, n))
                        rep.failures.append('warning regression: %s %s' % (p, code))
        if a.write_baseline:
            json.dump(counts, open(a.write_baseline, 'w'), indent=2, sort_keys=True)

        # Requirements
        modules = stock_module_libraries()
        providers = collections.defaultdict(set)
        registered = collections.defaultdict(set)
        for f in files:
            src = open(f, errors='replace').read()
            for lib in re.findall(r'register_library\s*\(\s*"([^"]+)"', src):
                providers[lib].add(names[f])
            for nat in re.findall(r'register_native\s*\(\s*"([^"]+)"', src):
                registered[nat].add(names[f])
        needs = {}
        for f, t in tables.items():
            libs = set(t['libraries']) | {v[4:] for v in t['tags'] if v.startswith('?rl_')}
            forced = {v[3:] for v in t['tags'] if v.startswith('?f_')}
            needs[names[f]] = (libs, forced)
            for lib in sorted(libs):
                if lib in providers:
                    rep.add('Requirements', '%s needs %s (plugin: %s)' % (names[f], lib, ', '.join(sorted(providers[lib]))))
                elif lib in modules:
                    rep.add('Requirements', '%s needs %s (module)' % (names[f], lib))
                else:
                    msg = 'needs library %s, which no linted plugin or stock module provides' % lib
                    rep.add('Unresolved requirements', '%s %s' % (names[f], msg))
                    rep.annotate('warning', f, 1, 'unresolved requirement', msg)
            if forced:
                rep.add('Requirements', '%s force-loads modules: %s' % (names[f], ', '.join(sorted(forced))))
        if a.plugins_ini:
            enabled = []
            for ini in a.plugins_ini:
                enabled += read_plugins_ini(ini)
            known = {n.lower(): n for n in needs}
            on = {known[e.lower()] for e in enabled if e.lower() in known}
            for e in enabled:
                if e.lower() not in known:
                    rep.add('plugins.ini', '%s is enabled but was not among the linted plugins' % e)
            for p in sorted(on):
                for lib in sorted(needs[p][0]):
                    if lib in providers and not (providers[lib] & on):
                        msg = '%s is enabled but needs %s, provided by %s, which is not enabled' % (p, lib, ', '.join(sorted(providers[lib])))
                        rep.add('plugins.ini', msg)
                        rep.failures.append('unresolved: ' + msg)
                        rep.annotate('error', a.plugins_ini[0], 1, 'missing plugin library', msg)

        # Natives no linted plugin calls
        used = set()
        for t in tables.values():
            used.update(t['natives'])
        for nat, who in sorted(registered.items()):
            if nat not in used:
                rep.add('Natives never called', '%s (registered by %s)' % (nat, ', '.join(sorted(who))))

        # Static checks
        on_disk = {}
        for d in [STOCK] + incdirs + (['include'] if os.path.isdir('include') else []):
            for n in os.listdir(d):
                on_disk.setdefault(n.lower(), n)
        for f in files:
            raw = open(f, 'rb').read()
            crlf, lf = raw.count(b'\r\n'), raw.count(b'\n') - raw.count(b'\r\n')
            if crlf and lf:
                last = ' (only the final line ends in LF)' if lf == 1 and raw.endswith(b'\n') and not raw.endswith(b'\r\n') else ''
                rep.add('Line endings', '%s mixes CRLF (%d) and LF (%d) line endings%s' % (f, crlf, lf, last))
                rep.annotate('warning', f, 1, 'mixed line endings', 'CRLF %d, LF %d%s' % (crlf, lf, last))
            for m in INC_RE.finditer(raw):
                inc = m.group(2).decode(errors='replace')
                fname = os.path.basename(inc if inc.endswith('.inc') else inc + '.inc')
                real = on_disk.get(fname.lower())
                if real and real != fname and m.group(1) == b'<':
                    line = raw.count(b'\n', 0, m.start()) + 1
                    rep.add('Include case', '%s:%d: <%s> should be <%s>' % (f, line, inc, os.path.splitext(real)[0]))
                    rep.annotate('warning', f, line, 'include case', '<%s> only matches %s on a case-insensitive filesystem' % (inc, real))

        # Removable includes
        if not a.no_includes:
            variants = []
            for f in files:
                if f not in images:
                    continue
                raw = open(f, 'rb').read()
                for i, m in enumerate(INC_RE.finditer(raw)):
                    d = os.path.join(work, names[f], str(i))
                    os.makedirs(d)
                    src = os.path.join(d, os.path.basename(f))
                    open(src, 'wb').write(raw[:m.start()] + b'//' + raw[m.start():])
                    variants.append((f, m.group(2).decode(errors='replace'), raw.count(b'\n', 0, m.start()) + 1, src))

            def var_job(v):
                f, _, _, src = v
                ok, _ = compile_to(src, src[:-4] + '.amxx', incdirs, ['-d0', '-i' + (os.path.dirname(f) or '.')])
                return ok
            for (f, inc, line, src), ok in zip(variants, parallel(var_job, variants, a.jobs)):
                if not ok:
                    continue
                v = amx_image(src[:-4] + '.amxx')
                if v == images[f]:
                    rep.add('Removable includes', '%s:%d: <%s> changes nothing (unused or already included)' % (f, line, inc))
                    continue
                tv, to = amx_tables(v), tables[f]
                if tv['code'] != to['code']:
                    continue
                gone = sorted(markers(to) - markers(tv))
                if gone:
                    msg = '<%s> is only a load-time requirement: %s' % (inc, ', '.join(gone))
                    rep.add('Removable includes', '%s:%d: %s' % (f, line, msg))
                    rep.annotate('notice', f, line, 'include only adds a requirement', msg)
                else:
                    rep.add('Removable includes', '%s:%d: <%s> changes nothing (symbol order only)' % (f, line, inc))
    finally:
        remove_tree(work)

    print('%d plugins, %d include paths' % (len(files), len(incdirs)))
    for section, lines in rep.sections.items():
        print('\n== %s (%d)' % (section, len(lines)))
        for line in lines:
            print('  ' + line)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        for level, f, line, title, msg in rep.annotations:
            print('::%s file=%s,line=%d,title=%s::%s' % (level, f, line, title, msg.replace('\n', ' ')))
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a') as s:
                s.write('## AMX Mod X lint\n\n%d plugins\n\n' % len(files))
                for section, lines in rep.sections.items():
                    s.write('<details><summary>%s (%d)</summary>\n\n```\n%s\n```\n</details>\n\n' % (section, len(lines), '\n'.join(lines)))
    if a.strict and rep.failures:
        print('\n%d failures (--strict)' % len(rep.failures))
        return 1
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, argv = sys.argv[1], sys.argv[2:]
    if cmd == 'compile':
        return cmd_compile(argv)
    if cmd == 'lint':
        return cmd_lint(argv)
    print('Unknown command: ' + cmd, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
