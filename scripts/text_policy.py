"""Elementos RAW que se conservan, compartidos por limpieza y traduccion/typeo."""
import re
import unicodedata

SOUNDS=frozenset('VRRR BRRR BRR BZZZ ZZZ TMP TAP CLING CLANG NUZZLE HAH SIGH SNIFF THUD THUMP BANG SLAM CLICK CLACK RUSTLE SWISH WHAM WHOOSH CRASH RING DING DONG GASP PEEK'.split())


def protected_reason(text,kind=None):
    if kind in {'sfx','sonido','onomatopeya'}:return 'sonido'
    if kind in {'numero_aislado','signo_aislado'}:return kind
    text=unicodedata.normalize('NFKC',text or '').strip()
    if not text:return None
    # Horas y cifras se conservan incluso con unidades AM/PM y puntuacion.
    numeric=re.sub(r'[ap]\.?\s*m\.?\s*$','',text.rstrip('!?¡¿.,… '),flags=re.I)
    if any(c.isdigit() for c in numeric) and not any(c.isalpha() for c in numeric):return 'numero_aislado'
    if not any(c.isalnum() for c in text) and all(c.isspace() or unicodedata.category(c).startswith('P') for c in text):return 'signo_aislado'
    words=re.findall(r'[A-Za-z]+',text.upper())
    if words and all(w in SOUNDS or re.fullmatch(r'[BV]R{2,}|BZ{2,}|Z{2,}|T[AO]P{2,}',w) for w in words):return 'sonido'
    return None
