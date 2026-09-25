"""
Gaming History (Android) - baca data 'gaming_logs' dari Firestore lewat REST API.

INI APP READ-ONLY. Tidak pernah menulis apa pun ke Firestore -> tidak butuh
service account, tidak butuh login. Syarat: security rules Firestore untuk
collection 'gaming_logs' harus "allow read: if true;" (dan write tetap
dikunci, hanya lewat service account di script desktop).

WAJIB DIISI sebelum build:
    PROJECT_ID = "isi-project-id-firebase-kamu"
"""

import threading

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle
from kivy.properties import ListProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.widget import Widget

# ============================================================
# KONFIGURASI - GANTI INI
# ============================================================
PROJECT_ID = "gamclas"
COLLECTION = "gaming_logs"
PAGE_SIZE = 30

BASE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

# ---- tema (sama seperti versi desktop) ----
BG_DARK = "#0d1117"
CARD_BG = "#161b22"
BORDER = "#30363d"
TEXT_LIGHT = "#e6edf3"
TEXT_MUTED = "#8b949e"
COLOR_GAMING = "#FF8C42"
COLOR_NON_GAMING = "#3DA5F5"


def hex_to_rgba(hex_color, alpha=1.0):
    hex_color = hex_color.lstrip('#')
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b, alpha)


def format_seconds(sec):
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def hms_to_seconds(text):
    h, m, s = (int(p) for p in text.split(':'))
    return h * 3600 + m * 60 + s


# ============================================================
# FIRESTORE REST API (tanpa firebase_admin, tanpa auth - baca publik)
# ============================================================
def _parse_value(v):
    """Ubah satu 'Value' Firestore REST JSON jadi tipe Python biasa."""
    if 'integerValue' in v:
        return int(v['integerValue'])
    if 'doubleValue' in v:
        return float(v['doubleValue'])
    if 'stringValue' in v:
        return v['stringValue']
    if 'booleanValue' in v:
        return v['booleanValue']
    if 'nullValue' in v:
        return None
    if 'timestampValue' in v:
        return v['timestampValue']
    if 'arrayValue' in v:
        return [_parse_value(x) for x in v['arrayValue'].get('values', [])]
    if 'mapValue' in v:
        return {k: _parse_value(x) for k, x in v['mapValue'].get('fields', {}).items()}
    return None


def _parse_fields(doc_json):
    return {k: _parse_value(v) for k, v in doc_json.get('fields', {}).items()}


def fetch_dates_page(page_token=None, page_size=PAGE_SIZE):
    """
    Ambil satu halaman daftar tanggal, terbaru dulu, beserta total ringkas
    (tanpa ikut timeline, biar ringan). Order pakai __name__ (nama dokumen)
    supaya urutannya konsisten dengan document ID (= tanggal).
    """
    params = {'pageSize': page_size, 'orderBy': '__name__ desc'}
    if page_token:
        params['pageToken'] = page_token

    resp = requests.get(f"{BASE_URL}/{COLLECTION}", params=params, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()

    results = []
    for doc in data.get('documents', []):
        date_str = doc['name'].split('/')[-1]
        fields = _parse_fields(doc)
        results.append({
            'date': date_str,
            'total_gaming_seconds': fields.get('total_gaming_seconds', 0) or 0,
            'total_non_gaming_seconds': fields.get('total_non_gaming_seconds', 0) or 0,
        })
    return results, data.get('nextPageToken')


def fetch_day_detail(date_str):
    """Ambil satu dokumen penuh (termasuk timeline) untuk satu tanggal."""
    resp = requests.get(f"{BASE_URL}/{COLLECTION}/{date_str}", timeout=15)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    return _parse_fields(resp.json())


# ============================================================
# WIDGET HELPER (card, label, separator) - dipakai berulang di kedua screen
# ============================================================
class Card(BoxLayout):
    """BoxLayout dengan background CARD_BG + garis tepi BORDER, mirip card di versi desktop."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*hex_to_rgba(CARD_BG))
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
            Color(*hex_to_rgba(BORDER))
            self._border_line = Line(rectangle=(self.x, self.y, self.width, self.height), width=1)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border_line.rectangle = (self.x, self.y, self.width, self.height)


class CardButton(ButtonBehavior, Card):
    """Card yang bisa ditekan - dipakai untuk baris di daftar history.
    Ini Layout asli (bukan Button biasa), jadi widget anak diatur otomatis
    dan tidak numpuk di pojok."""
    pass


class Separator(Widget):
    """Garis pembatas tipis horizontal, mirip ttk.Separator di versi desktop."""

    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (1, None))
        kwargs.setdefault('height', 1)
        super().__init__(**kwargs)
        with self.canvas:
            Color(*hex_to_rgba(BORDER))
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


def make_label(text, color_hex, font_size=13, bold=False, halign='left', valign='middle', **kwargs):
    """Label dengan text_size otomatis terikat ke ukurannya sendiri, supaya halign benar-benar berlaku."""
    lbl = Label(text=text, color=hex_to_rgba(color_hex), font_size=font_size, bold=bold,
                halign=halign, valign=valign, **kwargs)
    lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
    return lbl


def make_flat_button(text, bg_hex, fg_hex="#ffffff", **kwargs):
    btn = Button(text=text, background_normal='', background_down='',
                 background_color=hex_to_rgba(bg_hex), color=hex_to_rgba(fg_hex),
                 bold=True, **kwargs)
    return btn


def make_stat_card(title, color_hex):
    """Card dengan accent bar warna di kiri + judul + nilai besar, sama seperti versi desktop."""
    card = Card(orientation='horizontal', size_hint=(1, 1))

    accent = Widget(size_hint=(None, 1), width=5)
    with accent.canvas:
        Color(*hex_to_rgba(color_hex))
        accent_rect = Rectangle(pos=accent.pos, size=accent.size)
    accent.bind(pos=lambda inst, val: setattr(accent_rect, 'pos', val),
                size=lambda inst, val: setattr(accent_rect, 'size', val))
    card.add_widget(accent)

    inner = BoxLayout(orientation='vertical', padding=(16, 14), spacing=4)
    inner.add_widget(make_label(title, TEXT_MUTED, font_size=12, bold=True,
                                 size_hint=(1, None), height=18))
    value_label = make_label("00:00:00", color_hex, font_size=26, bold=True, size_hint=(1, 1))
    inner.add_widget(value_label)
    card.add_widget(inner)
    return card, value_label


# ============================================================
# WIDGET TIMELINE (canvas sederhana, mirip versi desktop)
# ============================================================
class TimelineWidget(Widget):
    segments = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, segments=self._redraw)

    def _redraw(self, *args):
        self.canvas.clear()
        with self.canvas:
            Color(*hex_to_rgba(CARD_BG))
            Rectangle(pos=self.pos, size=self.size)

            for seg in self.segments:
                state = seg.get('state')
                if state == 'GAMING':
                    color = COLOR_GAMING
                elif state == 'NON-GAMING':
                    color = COLOR_NON_GAMING
                else:
                    continue
                try:
                    start = hms_to_seconds(seg['start'])
                    end = hms_to_seconds(seg['end'])
                except (KeyError, ValueError, AttributeError, TypeError):
                    continue

                x1 = self.x + (start / 86400.0) * self.width
                x2 = self.x + (end / 86400.0) * self.width
                Color(*hex_to_rgba(color))
                Rectangle(pos=(x1, self.y), size=(max(x2 - x1, 2), self.height))

            # garis tepi, mirip highlightbackground di versi desktop
            Color(*hex_to_rgba(BORDER))
            Line(rectangle=(self.x, self.y, self.width, self.height), width=1)


# ============================================================
# SCREEN 1: DAFTAR TANGGAL (HISTORY)
# ============================================================
class HistoryListScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.next_page_token = None
        self.loading = False

        root = BoxLayout(orientation='vertical')
        with root.canvas.before:
            Color(*hex_to_rgba(BG_DARK))
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        header = BoxLayout(size_hint=(1, None), height=64, padding=(18, 10), spacing=10)
        title_box = BoxLayout(orientation='vertical')
        title_box.add_widget(make_label("GAMING HISTORY", TEXT_LIGHT, font_size=20, bold=True,
                                         size_hint=(1, None), height=26))
        title_box.add_widget(make_label("Ketuk tanggal untuk lihat detail", TEXT_MUTED, font_size=12,
                                         size_hint=(1, None), height=16))
        header.add_widget(title_box)

        refresh_btn = make_flat_button("Refresh", COLOR_NON_GAMING, size_hint=(None, None),
                                        size=(100, 40), pos_hint={'center_y': 0.5})
        refresh_btn.bind(on_release=lambda *_: self.refresh(reset=True))
        header.add_widget(refresh_btn)
        root.add_widget(header)

        root.add_widget(Separator())

        self.status_label = make_label("Memuat...", TEXT_MUTED, font_size=12,
                                         size_hint=(1, None), height=28,
                                         padding=(18, 0))
        root.add_widget(self.status_label)

        self.scroll = ScrollView()
        self.rows = GridLayout(cols=1, size_hint_y=None, spacing=8, padding=(14, 4, 14, 12))
        self.rows.bind(minimum_height=self.rows.setter('height'))
        self.scroll.add_widget(self.rows)
        root.add_widget(self.scroll)

        self.load_more_btn = make_flat_button("Muat lebih banyak", CARD_BG, fg_hex=TEXT_LIGHT,
                                               size_hint=(1, None), height=48)
        self.load_more_btn.bind(on_release=lambda *_: self.refresh(reset=False))
        self.load_more_btn.opacity = 0
        self.load_more_btn.disabled = True
        root.add_widget(self.load_more_btn)

        self.add_widget(root)

    def _sync_bg(self, instance, *args):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def on_pre_enter(self):
        if not self.rows.children:
            self.refresh(reset=True)

    def refresh(self, reset=True):
        if self.loading:
            return
        self.loading = True
        self.status_label.text = "Memuat..."
        page_token = None if reset else self.next_page_token
        threading.Thread(target=self._fetch_worker, args=(reset, page_token), daemon=True).start()

    def _fetch_worker(self, reset, page_token):
        try:
            results, next_token = fetch_dates_page(page_token=page_token)
            Clock.schedule_once(lambda dt: self._on_fetched(results, next_token, reset))
        except Exception as e:
            message = str(e)
            Clock.schedule_once(lambda dt: self._on_error(message))

    def _on_fetched(self, results, next_token, reset):
        self.loading = False
        if reset:
            self.rows.clear_widgets()

        for item in results:
            self.rows.add_widget(self._make_row(item))

        self.next_page_token = next_token
        self.load_more_btn.opacity = 1 if next_token else 0
        self.load_more_btn.disabled = not next_token

        count = len(self.rows.children)
        self.status_label.text = f"{count} hari dimuat." if count else "Belum ada data."

    def _on_error(self, message):
        self.loading = False
        self.status_label.text = f"Gagal memuat: {message}"

    def _make_row(self, item):
        row = CardButton(orientation='vertical', size_hint=(1, None), height=68,
                          padding=(14, 10), spacing=6)
        row.bind(on_release=lambda *_: self._open_detail(item['date']))

        row.add_widget(make_label(item['date'], TEXT_LIGHT, font_size=15, bold=True,
                                   size_hint=(1, None), height=22))

        totals = BoxLayout(size_hint=(1, None), height=18, spacing=16)
        totals.add_widget(make_label(
            f"Gaming {format_seconds(item['total_gaming_seconds'])}",
            COLOR_GAMING, font_size=13))
        totals.add_widget(make_label(
            f"Non-Gaming {format_seconds(item['total_non_gaming_seconds'])}",
            COLOR_NON_GAMING, font_size=13))
        row.add_widget(totals)

        return row

    def _open_detail(self, date_str):
        detail = self.manager.get_screen('detail')
        detail.load_date(date_str)
        self.manager.current = 'detail'


# ============================================================
# SCREEN 2: DETAIL SATU HARI
# ============================================================
class DayDetailScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(orientation='vertical')
        with root.canvas.before:
            Color(*hex_to_rgba(BG_DARK))
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        header = BoxLayout(size_hint=(1, None), height=64, padding=(18, 10), spacing=12)
        back_btn = make_flat_button("< Kembali", CARD_BG, fg_hex=TEXT_LIGHT,
                                     size_hint=(None, None), size=(110, 40),
                                     pos_hint={'center_y': 0.5})
        back_btn.bind(on_release=lambda *_: setattr(self.manager, 'current', 'history'))
        header.add_widget(back_btn)
        self.title_label = make_label("", TEXT_LIGHT, font_size=18, bold=True)
        header.add_widget(self.title_label)
        root.add_widget(header)

        root.add_widget(Separator())

        self.status_label = make_label("", TEXT_MUTED, font_size=12,
                                         size_hint=(1, None), height=28, padding=(18, 0))
        root.add_widget(self.status_label)

        tl_wrap = BoxLayout(padding=(18, 6), size_hint=(1, None), height=76)
        self.timeline = TimelineWidget()
        tl_wrap.add_widget(self.timeline)
        root.add_widget(tl_wrap)

        totals_row = BoxLayout(size_hint=(1, None), height=90, padding=(18, 4), spacing=12)
        gaming_card, self.gaming_value = make_stat_card("GAMING", COLOR_GAMING)
        non_gaming_card, self.non_gaming_value = make_stat_card("NON-GAMING", COLOR_NON_GAMING)
        totals_row.add_widget(gaming_card)
        totals_row.add_widget(non_gaming_card)
        root.add_widget(totals_row)

        root.add_widget(Widget())  # filler agar tidak menempel ke bawah

        self.add_widget(root)

    def _sync_bg(self, instance, *args):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def load_date(self, date_str):
        self.title_label.text = date_str
        self.status_label.text = "Memuat..."
        self.timeline.segments = []
        self.gaming_value.text = "00:00:00"
        self.non_gaming_value.text = "00:00:00"
        threading.Thread(target=self._fetch_worker, args=(date_str,), daemon=True).start()

    def _fetch_worker(self, date_str):
        try:
            fields = fetch_day_detail(date_str)
            Clock.schedule_once(lambda dt: self._on_loaded(date_str, fields))
        except Exception as e:
            message = str(e)
            Clock.schedule_once(lambda dt: self._on_error(message))

    def _on_loaded(self, date_str, fields):
        if fields is None:
            self.status_label.text = f"Tidak ada data untuk {date_str}."
            return

        segments = fields.get('timeline', []) or []
        self.timeline.segments = segments
        self.gaming_value.text = format_seconds(fields.get('total_gaming_seconds', 0))
        self.non_gaming_value.text = format_seconds(fields.get('total_non_gaming_seconds', 0))
        self.status_label.text = f"{len(segments)} segmen."

    def _on_error(self, message):
        self.status_label.text = f"Gagal memuat: {message}"


# ============================================================
# APP
# ============================================================
class GamingHistoryApp(App):
    def build(self):
        sm = ScreenManager()
        sm.add_widget(HistoryListScreen(name='history'))
        sm.add_widget(DayDetailScreen(name='detail'))
        return sm


if __name__ == '__main__':
    GamingHistoryApp().run()