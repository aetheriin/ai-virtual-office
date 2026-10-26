# AI Virtual Office & Trading Hub

Kantor virtual 3D isometrik berisi tim agen AI yang bekerja otonom:

- **Departemen IT** — PM → Analis Kebutuhan → Database → Backend → Frontend → QA.
- **Departemen Investasi (Intraday Arena)** — Bull Agent vs Bear Agent berdebat, Risk Agent memutuskan **BUY / SELL / WAIT** lewat kartu *Trading Plan*.

![Intraday Arena](docs/screenshot-arena.png)
![Departemen IT](docs/screenshot-it.png)

## Arsitektur

```
Next.js + Tailwind + React Three Fiber  ◀── Socket.IO ──▶  FastAPI + python-socketio
  (avatar, chat bubble, kanban, plan card)                    ├─ agents/it_department.py  (PM/BA/DB/BE/FE/QA)
                                                              ├─ agents/trading.py        (Bull/Bear/Risk)
                                                              ├─ market/data.py           (MT5 → yfinance → Twelve Data → sintetis)
                                                              ├─ market/indicators.py     (struktur, S/R, ATR, volume, wick)
                                                              ├─ market/news.py           (sentimen berita: Alpha Vantage, Finnhub, RSS, yfinance)
                                                              ├─ risk.py                  (RR, ukuran posisi, tick IDX)
                                                              ├─ llm.py                   (OpenRouter + Google AI Studio)
                                                              ├─ projects/                (PostgreSQL: proyek, sprint, task, kode, temuan QA)
                                                              └─ db.py                    (SQLite: log debat & plan)
```

### Prinsip penting

- **Angka tidak pernah dari LLM.** Entry, SL, TP, RR, dan ukuran posisi dihitung deterministik dari data candle. LLM hanya menulis argumen, dan Risk Agent (LLM) hanya boleh *menurunkan* keputusan menjadi WAIT, tidak boleh membuka posisi baru.
- **Hak veto Risk Agent** (aturan keras): batas rugi harian, volatilitas ekstrem (ATR%), selisih bukti Bull/Bear < 2 poin, RR TP2 < `MIN_RR` (default 1:1.5), TP1 < 1R, sentimen berita kuat yang berlawanan, atau modal tidak cukup untuk 1 lot.
- **Jalan tanpa API key.** Tanpa key, semua agen memakai *rule engine* (badge `RULE ENGINE`). Jika sumber data live tidak terjangkau, data sintetis dipakai dan kartu diberi label **DATA SINTETIS — JANGAN dieksekusi**.
- Rahasia hanya di `.env` (lihat `.env.example`).

## Menjalankan

### 1. Database PostgreSQL

```bash
cp .env.example .env            # isi OPENROUTER_API_KEY / GEMINI_API_KEY bila ada
docker compose up -d            # PostgreSQL 16 di localhost:5432 (user/pass/db: office)
```

Tanpa Docker: pakai PostgreSQL yang sudah ada dan isi `DATABASE_URL`. Kalau `DATABASE_URL` dikosongkan, backend otomatis memakai file SQLite `backend/projects.db`, jadi aplikasi tetap jalan tanpa server database.

### 2. Backend (Python 3.11+)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:asgi --reload --port 8000
```

Opsional untuk forex real-time di Windows: `pip install MetaTrader5` dan buka terminal MT5. Sumber data lalu dipakai otomatis sesuai urutan MT5 → yfinance → Twelve Data.

### 3. Frontend (Node 20+)

```bash
cd frontend
cp .env.local.example .env.local   # NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm install
npm run dev                         # http://localhost:3000
```

### 4. Tes

```bash
cd backend && pytest -q             # 139 tes: risk math, aturan BEI, debat, screener, jurnal, berita, pipeline IT, database, PR GitHub (offline)
# tes database juga terhadap PostgreSQL sungguhan (skema di DB ini akan di-reset):
TEST_DATABASE_URL=postgresql://office:office@localhost:5432/office_test pytest -q tests/test_projects.py
cd frontend && npm test && npm run typecheck && npm run build   # npm test: logika avatar .glb (Node 22+)
```

## Database proyek IT (PostgreSQL)

Sesuai master plan, data dipisah dua:
- **SQLite** menyimpan log debat dan memori agen.
- **PostgreSQL** menyimpan data proyek IT, yaitu tabel berikut.

| Tabel | Isi |
|---|---|
| `projects` | proyek (nama unik, deskripsi, repo GitHub + branch dasar) |
| `it_runs` | satu sprint per brief: prompt, status `running/done/failed`, ringkasan PM, asumsi, analisis, review QA (JSONB), dan status/URL pull request |
| `it_tasks` | papan tugas per sprint: kode T1…, assignee, dependensi, kriteria selesai, status `todo/doing/done` |
| `it_artifacts` | file kode dari agen DB/BE/FE: path, bahasa (`sql`, `python`, `tsx`, …), isi |
| `qa_findings` | temuan QA per tingkat (`high/medium/low`) |

- **Tersimpan otomatis.** Status papan tugas disimpan saat agen bekerja. Sprint yang gagal tetap tercatat beserta errornya.
- **Memori proyek.** Saat brief baru masuk, PM menerima konteks 5 sprint terakhir dan temuan QA *high* di proyek itu, jadi sprint berikutnya melanjutkan pekerjaan yang ada.
- **Di UI.** Panel Dept. IT punya pemilih proyek, tombol **+ Baru**, dan **Riwayat Sprint** untuk membuka ulang hasil sprint lama.
- **Migrasi.** Alembic menjalankannya otomatis saat startup (`DB_AUTO_MIGRATE=true`). Lewat CLI, dari folder `backend/`:

```bash
alembic upgrade head                               # terapkan migrasi
alembic revision --autogenerate -m "tambah kolom"  # buat migrasi baru setelah mengubah app/projects/models.py
alembic check                                      # pastikan model == migrasi
```

## Departemen Investasi: Analisa, Screener & Jurnal

Panel **DEPT. INVESTASI** punya tiga sub-tab:

### Analisa (satu instrumen)
- **Watchlist.** Klik kode saham/pair untuk langsung analisa. Klik **ATUR WATCHLIST** untuk menambah atau menghapus (mis. `BUVA`, `BUMI`). Kode saham BEI cukup diketik tanpa `.JK`.
- **Kode salah = error jelas.** `ALLOW_SYNTHETIC_DATA=false` (default) membuat kode yang tidak ada memunculkan pesan "tidak ditemukan", bukan diam-diam memakai data palsu. Saham dengan candle terlalu sedikit diberi saran pindah ke timeframe `1h`/`1d`.
- **Aturan BEI.**
  - **TP dibatasi ARA.** Target dipotong di batas ARA hari itu (dari harga penutupan kemarin), karena harga tidak bisa naik melewatinya.
  - **SL di bawah ARB diberi peringatan.** SL di bawah ARB tidak bisa tersentuh hari itu, jadi ada risiko gap besok.
  - **Default mengikuti aturan BEI per Oktober 2026:** ARA 35/25/20% sesuai harga; ARB 7% (Rp1 untuk saham Rp11–14) s.d. 31 Des 2026, lalu simetris mulai 2027. Aturan ini sering berubah, jadi ganti lewat `IDX_ARA_PCT`/`IDX_ARB_PCT` bila perlu.
  - **Papan Akselerasi & Pemantauan Khusus belum dimodelkan.**
- **Saham tidak bisa short.** Bias turun pada saham ditampilkan sebagai **HINDARI** (bukan sinyal jual-kosong).
- **Veto data basi.** Analisa saat bursa buka tapi candle terakhir sudah lama ditolak. Analisa di luar jam bursa diberi peringatan. Jam BEI dihitung dalam WIB, termasuk istirahat Jumat. Libur bursa belum dikenali.
- **Likuiditas.**
  - Nilai transaksi harian rata-rata < `MIN_DAILY_VALUE_IDR` (default Rp1 M) → veto.
  - Di bawah `WARN_DAILY_VALUE_IDR` → peringatan.
  - Ukuran posisi > 1% nilai transaksi harian → peringatan slippage.
- **MetaTrader5.** Nama simbol broker dideteksi otomatis (`XAUUSDm`, `XAUUSD.r`, `XAUUSD-ECN`, … dipilih yang terpendek). Bisa dipaksa lewat `MT5_SYMBOL_MAP={"XAUUSD":"XAUUSDm"}` atau `MT5_SYMBOL_SUFFIX`.

### Screener: rekomendasi beli otomatis
Klik **Cari Saham Layak Beli**:
1. Sistem memindai daftar saham (default ±50 saham BEI besar yang sering ditransaksikan; *bukan* daftar indeks resmi, ubah lewat **UBAH DAFTAR**).
2. Setiap saham dianalisa dengan aturan yang sama persis dengan Analisa, tanpa LLM supaya cepat dan gratis.
3. Hasilnya:
   - **Rekomendasi beli**: hanya saham yang lolos semua veto Risk Agent, diurutkan menurut skor (selisih bukti Bull−Bear, RR, likuiditas), lengkap dengan harga beli, SL, TP1/TP2, RR, dan jumlah lot sesuai modal & risiko.
   - **Pantau**: bullish tapi belum lolos (RR, ARA, likuiditas, dll.).
   - **Hindari**: tren turun.
4. Tombol **Debat-kan** menjalankan analisa lengkap (Bull vs Bear + berita) untuk satu kandidat.
5. 3 rekomendasi teratas otomatis dicatat di Jurnal, supaya akurasi screener ikut terukur.

Aturannya ketat, jadi **screener sering tidak merekomendasikan apa pun.** Itu wajar: Risk Agent menolak beli tepat di bawah resistance (TP1 < `MIN_RR_TP1`), saat data basi, atau saham tidak likuid. Melonggarkan `MIN_RR_TP1` menambah jumlah sinyal. Pakai Jurnal untuk melihat apakah sinyal tambahan itu benar-benar menguntungkan.

### Jurnal paper trading
- **Tercatat otomatis.** Setiap plan **BUY/SELL** dari data asli (Analisa, dan 3 teratas Screener) dicatat sebagai trade kertas.
- **Dinilai otomatis.** Tiap `JOURNAL_REFRESH_MIN` menit (default 15), atau lewat **Cek hasil sekarang**, sistem mengecek candle berikutnya.
- **Model eksekusi:**
  - Masuk di harga entry.
  - Separuh posisi keluar di TP1, stop sisanya pindah ke harga beli (*break-even*), sisanya menargetkan TP2.
  - Bila satu candle menyentuh stop dan target sekaligus, dianggap kena stop (konservatif).
  - Trade kedaluwarsa setelah 48 jam (intraday) / 10 hari (`1d`).
- **Statistik:** jumlah tertutup, win rate, rata-rata dan total **R** (kelipatan risiko), serta P/L kertas dalam rupiah.
- **Butuh minimal ~30 trade tertutup** sebelum angka ini berarti. Plan dari data sintetis tidak pernah dicatat.

> ⚠️ Rekomendasi screener adalah hasil pemindaian teknikal otomatis, **bukan saran investasi**. Uji dulu lewat Jurnal sebelum memakai uang sungguhan.

## Pull request otomatis (Departemen IT → GitHub)

Hubungkan proyek ke repo GitHub, dan setiap sprint selesai dengan **pull request** berisi kode dari agen DB/BE/FE. Anda tinggal review di GitHub lalu merge.

**1. Buat token GitHub** di GitHub → Settings → Developer settings → *Fine-grained tokens*, lalu isi sebagai `GITHUB_TOKEN` di `.env`.

| Pengaturan token | Isi |
|---|---|
| Repository access | **Only select repositories**: pilih repo yang akan dihubungkan |
| Contents | Read and write |
| Pull requests | Read and write |
| Metadata | Read (otomatis) |
| Issues | Read and write (opsional, untuk label `ai-agent`) |

**2. Hubungkan proyek.** Di panel Dept. IT, isi *Repo GitHub* (`owner/nama`) saat membuat proyek, atau klik **HUBUNGKAN** pada proyek yang sudah ada. Backend langsung mengecek apakah token bisa menulis ke repo itu.

**3. Kirim brief.** Alurnya:
1. PM dan agen membaca struktur repo dan file kunci (README, `package.json`, `requirements.txt`, …).
2. Coder menulis kode per file (`### FILE: path`), dan file yang akan diubah dibaca dulu isinya.
3. Setelah QA, sistem membuat branch `ai/<brief>-<id>`, satu commit, dan PR. Deskripsi PR berisi brief, rencana PM, asumsi, acceptance criteria, daftar file, dan hasil review QA.

**Web baru = repo kosong baru.** Buat repo kosong di GitHub (tanpa README), tambahkan ke token, lalu hubungkan ke proyek baru. Karena GitHub tidak bisa membuat branch di repo tanpa commit, sistem membuat satu commit `README.md` di branch utama. Setelah itu kerangka proyeknya tetap masuk lewat PR.

**Pengaman (ditegakkan oleh kode, bukan diserahkan ke model):**
- **Tidak pernah push ke branch utama.** Satu-satunya pengecualian adalah README awal untuk repo kosong. Merge selalu manual oleh Anda.
- **Draft bila QA belum lolos.** PR dibuka sebagai **draft** kalau QA tidak `PASS` atau ada temuan *high*. Di repo privat akun gratis, GitHub tidak mendukung draft, jadi PR dibuka biasa dengan judul `[WIP]`.
- **File berbahaya ditolak.** File `.env`/kunci privat, folder `.git`, workflow `.github/workflows/`, path `..`/absolut, dan file > `PR_MAX_FILE_KB` tidak disertakan. Daftarnya ditulis di deskripsi PR.
- **Template tidak dikirim.** Tanpa LLM (mode *rule engine*), kodenya hanya template generik, jadi PR **tidak** dibuat kecuali `ALLOW_TEMPLATE_PR=true` (untuk uji coba di repo percobaan).
- **Gangguan GitHub tidak menggagalkan sprint.** Kalau repo tidak bisa dibaca atau GitHub bermasalah, sprint tetap selesai dan alasannya tercatat (`pr.status = failed`).

Status PR (`pending/opened/draft/skipped/failed`, URL, nomor, branch) tersimpan di tabel `it_runs` dan tampil di panel serta riwayat sprint.

## Sentimen berita

Setiap analisa menarik berita dari sumber yang tersedia (digabung, duplikat dibuang, maks. `NEWS_LOOKBACK_HOURS` jam):

| Sumber | Key | Cakupan |
|---|---|---|
| Alpha Vantage `NEWS_SENTIMENT` | `ALPHA_VANTAGE_API_KEY` | forex, memakai skor sentimen per mata uang dari Alpha Vantage |
| Finnhub forex news | `FINNHUB_API_KEY` | forex |
| RSS (default FXStreet & Investing.com) | tanpa key | forex, emas |
| yfinance `Ticker.news` | tanpa key | saham IDX |

**Cara menilai:**
- **Arah per pair.** Untuk pair BASE/QUOTE, skor berita = sentimen(BASE) − sentimen(QUOTE). Contohnya, "Fed dovish" dihitung bearish untuk USD, jadi bullish untuk XAUUSD/EURUSD dan bearish untuk USDJPY. Judul yang menyebut dua mata uang dinilai per klausa ("Gold slumps *as* dollar strength returns" → bearish emas).
- **Skor per judul.** Urutan prioritas: skor Alpha Vantage, lalu LLM (`MODEL_DEBATE`, bila `NEWS_USE_LLM=true`), lalu leksikon kata kunci. Agregatnya rata-rata berbobot waktu (half-life 6 jam), dalam rentang −1…+1.
- **Pengaruh ke debat:**
  - Sentimen ≥ ±0.15 dari minimal 2 berita menambah **maks. 1.5 poin** bukti ke Bull atau Bear. Bobot ini sengaja lebih kecil daripada struktur harga (2 poin).
  - Risk Agent **memveto** trade jika sentimen kuat (≥ ±0.4, minimal 3 berita) berlawanan arah.
  - Rilis berdampak tinggi (NFP/CPI/FOMC/keputusan bank sentral) dalam 3 jam terakhir menjadi risiko Bear sekaligus peringatan di plan.
- **Tampilan.** Panel menampilkan gauge sentimen dan daftar judul (skor, sumber, umur, metode AV/AI/KW). Di ruang trading 3D ada *ticker* berita berjalan.

## Model per peran

Semua model bisa diganti lewat `.env`. ID model gratis di OpenRouter sering berubah, jadi cek https://openrouter.ai/models?q=free.

| Peran | Variabel | Default |
|---|---|---|
| PM, Analis, QA | `MODEL_PM` (+ `GEMINI_MODEL` bila `GEMINI_API_KEY` diisi) | `google/gemma-3-27b-it:free` / `gemini-2.5-flash` |
| Risk Agent | `MODEL_RISK` (+ Gemini) | `google/gemma-3-27b-it:free` |
| DB / BE / FE | `MODEL_CODER` | `qwen/qwen-2.5-coder-32b-instruct:free` |
| Bull & Bear | `MODEL_DEBATE` | `meta-llama/llama-3.1-8b-instruct:free` |

> Catatan: `google/gemini-1.5-pro`, `google/gemma-31b-it:free`, dan `poolside/laguna-s-2.1:free` dari master plan tidak dijadikan default karena ketersediaannya tidak bisa saya pastikan. Silakan isi ke `.env` bila ID tersebut aktif di akun Anda.

## Simbol yang didukung

- Saham IDX: ketik kode saja (`BBCA`, `TLKM`, …), otomatis jadi `BBCA.JK`. Ukuran posisi dalam **lot (100 lembar)** dan harga dibulatkan ke fraksi harga BEI.
- Forex/komoditas: `XAUUSD`, `XAGUSD`, `EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDIDR`, `BTCUSD`. Ukuran posisi dalam lot standar (100.000 unit; emas 100 oz).
- Akun IDR untuk instrumen USD memakai kurs asumsi `USD_IDR_RATE` (default 16.000) dan asumsi ini dicantumkan di kartu.

## API

| Method | Path | Keterangan |
|---|---|---|
| GET | `/api/health` | status, LLM aktif, departemen sibuk |
| POST | `/api/trade/analyze` | `{symbol, interval, capital, risk_pct, today_loss_pct, account_currency}` |
| POST | `/api/it/request` | `{prompt, project_id?}`; tanpa `project_id` masuk ke proyek "Umum" |
| GET | `/api/sessions`, `/api/sessions/{id}` | riwayat & log debat (SQLite) |
| GET | `/api/plans?symbol=BBCA` | riwayat trading plan |
| GET | `/api/news/{symbol}` | sentimen berita saja (tanpa debat) |
| GET / PUT | `/api/watchlist` | daftar tombol cepat `{symbols}` |
| POST | `/api/screener/run` | `{interval, symbols?, capital?, risk_pct?}`; hasil lewat event `screener:result` |
| GET | `/api/screener/last` | hasil screener terakhir |
| GET / PUT | `/api/screener/universe` | daftar saham yang dipindai |
| GET | `/api/journal` | trade kertas + statistik |
| POST | `/api/journal/refresh` | nilai ulang trade terbuka sekarang |
| DELETE | `/api/journal/{id}` | hapus trade kertas |
| GET / POST | `/api/projects` | daftar / buat proyek `{name, description, repo?, base_branch?}` |
| DELETE | `/api/projects/{id}` | hapus proyek beserta semua sprint-nya |
| PATCH | `/api/projects/{id}` | `{repo, base_branch, description}`; `repo: ""` melepas repo |
| GET | `/api/github/status` | apakah `GITHUB_TOKEN` diatur dan valid |
| GET | `/api/projects/{id}/runs` | riwayat sprint proyek |
| GET | `/api/it/runs/{id}` | detail sprint: task, kode, temuan QA |

Event Socket.IO: `agent:status`, `agent:message`, `it:tasks`, `it:task_status`, `it:result`, `it:pr`, `trade:market`, `trade:news`, `trade:plan`, `screener:progress`, `screener:result`, `journal:update`, `job:start|end|error`.

## Avatar 3D (.glb)

Secara default setiap agen memakai avatar voxel prosedural (banteng, beruang, orb hakim, staf IT). Agen mana pun bisa diganti dengan model **.glb** tanpa build ulang: taruh file di `frontend/public/avatars/`, lalu daftarkan di `frontend/public/avatars/manifest.json`.

```json
{
  "defaults": { "animations": ["/avatars/mixamo-pack.glb"] },
  "agents": {
    "pm":   { "url": "/avatars/pm.glb", "height": 1.8 },
    "qa":   { "url": "/avatars/qa.glb", "offset": [0, -0.3, 0.25] },
    "bull": { "url": "/avatars/bull.glb", "height": 2.4, "clips": { "debating": "Arguing" } }
  }
}
```

| Field | Arti |
|---|---|
| `url` | file .glb avatar (wajib) |
| `height` | tinggi target dalam meter; model diskalakan dan diletakkan otomatis di lantai (default 1.85) |
| `animations` | file klip tambahan, misalnya ekspor Mixamo; digabung dengan klip bawaan model |
| `clips` | paksa klip per state: `idle`, `sitting`, `typing`, `thinking`, `standing`, `debating` |
| `offset`, `rotationY` | koreksi posisi dan arah hadap (mis. agen yang duduk di kursi) |
| `rootMotion` | pertahankan track posisi Hips dari klip eksternal (default mati karena Mixamo menyimpannya dalam cm) |

Cara kerjanya:
- **Animasi per state.** Klip dipilih otomatis dari namanya, misalnya *Typing* untuk agen yang mengetik, *Thinking* saat berpikir, *Talking* saat berdiri atau berdebat, dan *Sitting* untuk agen duduk yang sedang idle. Pergantian klip memakai cross-fade.
- **Retarget Mixamo.** Prefix tulang `mixamorig` dibuang sehingga klip Mixamo cocok dengan rig bernama standar (`Hips`, `Spine`, `LeftArm`, …).
- **Lip-sync berbasis teks.** Mulut bergerak mengikuti huruf di *chat bubble* lewat morph `mouthOpen`/`jawOpen` atau viseme Oculus (`viseme_aa`, `viseme_O`, …), plus kedipan otomatis lewat `eyeBlinkLeft/Right`. Rhubarb belum dipakai karena butuh audio, dan aplikasi ini belum punya TTS.
- **Aman dari file rusak.** File yang tidak ada dilewati dengan peringatan di console. File rusak otomatis kembali ke avatar voxel.
- **Log diagnosis.** Console browser menampilkan baris `[avatar] pm: … · 5 clip (…) · lip-sync: mouthOpen` untuk tiap avatar yang dimuat.

**Contoh siap pakai:** salin `manifest.example.json` menjadi `manifest.json` untuk mencoba `sample-bot.glb` dan `sample-anims.glb`. Kedua file ini dibuat oleh `npm run avatars:sample` (skrip Python, tanpa download, bebas lisensi) dan meniru susunan avatar ber-rig Mixamo + klip Mixamo terpisah.

**Sumber avatar:**
- **Ready Player Me sudah menutup layanan publiknya pada 31 Januari 2026.** File .glb RPM yang sudah Anda unduh tetap bisa dipakai, tapi avatar baru tidak bisa dibuat lagi di sana.
- **Alternatif:** generator yang mengekspor .glb dengan tulang bernama Mixamo, misalnya Avaturn atau MetaPerson, seharusnya langsung cocok. Ini belum saya uji dengan file asli dari layanan tersebut.
- **Animasi:** unduh dari Mixamo (FBX), konversi ke .glb (misalnya lewat Blender), lalu daftarkan di `animations`.
- **VRM / VRoid:** nama tulangnya berbeda dan belum didukung retarget otomatis.

## Roadmap

- Suara (TTS) + lip-sync Rhubarb berbasis audio; retarget rig VRM/VRoid.
- Akun pengguna & login (tabel `users` di PostgreSQL).
- Agen memperbaiki PR sendiri dari komentar review & hasil CI GitHub.
- Backtest aturan Bull/Bear/Risk ke data historis; kalender libur BEI; screener terjadwal sebelum bursa buka.

> ⚠️ Bukan saran keuangan. Trading Plan adalah alat bantu analisa; selalu verifikasi sendiri sebelum eksekusi di MetaTrader/sekuritas.
