// CATATAN UNTUK PEMULA:
// File berakhiran .jsx berisi komponen React. JSX adalah cara menulis tampilan
// HTML LANGSUNG di dalam kode JavaScript — perhatikan tag <div>, <button>, dll
// di dalam fungsi di bawah.
//
// Konsep dasar React:
// - Komponen : satu bagian tampilan yang bisa dipakai ulang, ditulis sebagai fungsi.
// - state    : data yang bisa berubah. Setiap kali state berubah, React OTOMATIS
//              menggambar ulang tampilan agar sesuai. Kita tidak perlu menyentuh
//              elemen HTML satu per satu seperti pada JavaScript biasa.
// - props    : data yang dikirim dari komponen induk ke komponen anak.
//
// File App.jsx ini adalah komponen INDUK: ia mengurus tab navigasi di atas dan
// menentukan halaman mana yang ditampilkan.

// useState dan useEffect disebut "hook": fungsi khusus React untuk mengelola
// state dan efek samping.
import React, { useEffect, useState } from "react";
// Mengambil komponen halaman dari file-file lain.
import Monitor from "./pages/Monitor.jsx";
import Settings from "./pages/Settings.jsx";
import Dataset from "./pages/Dataset.jsx";
import Annotate from "./pages/Annotate.jsx";
import Training from "./pages/Training.jsx";
// Mengambil fungsi-fungsi komunikasi server dari api.js.
import { subscribeStatus, estop, clearEstop, setMode } from "./api.js";

// "export default" artinya inilah isi utama file ini yang dipakai file lain.
export default function App() {
  // useState mengembalikan DUA hal sekaligus, ditampung dengan kurung siku:
  //   tab    = nilai sekarang
  //   setTab = fungsi untuk mengubah nilainya
  // Nilai di dalam useState("monitor") adalah nilai awal.
  // PENTING: mengubah state HARUS lewat setTab(...), tidak boleh tab = "..."
  // karena React perlu tahu ada perubahan agar bisa menggambar ulang layar.
  const [tab, setTab] = useState("monitor");        // tab yang sedang dibuka
  const [status, setStatus] = useState(null);       // data status dari server
  const [annotateImg, setAnnotateImg] = useState(null);  // foto yang akan dianotasi

  // useEffect menjalankan kode "efek samping" (di luar penggambaran layar),
  // contohnya menyambung ke server.
  // Daftar kosong [] di akhir artinya: jalankan SEKALI SAJA saat komponen
  // pertama muncul. Kalau [] dihapus, ia akan jalan tiap penggambaran ulang —
  // dan itu berarti ratusan koneksi WebSocket menumpuk.
  // Fungsi yang dikembalikan subscribeStatus dipakai React untuk membersihkan
  // koneksi saat halaman ditutup.
  useEffect(() => subscribeStatus(setStatus), []);

  // Tanda !! mengubah nilai apa pun menjadi true/false murni.
  // Kalau status masih null (belum ada data) -> online bernilai false.
  const online = !!status;
  // Tanda tanya pada status?.manual_mode disebut "optional chaining":
  // ambil manual_mode HANYA kalau status ada isinya. Tanpa tanda tanya,
  // program error saat status masih null di detik-detik awal.
  const manual = status?.manual_mode;
  const isEstop = status?.estop;

  // return berisi tampilan yang akan digambar ke layar.
  // Di JSX, "class" HTML ditulis "className" karena "class" sudah punya arti
  // khusus di JavaScript.
  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <span className="logo">🐉</span>
          <span className="name">PemilahBuahNaga</span>
        </div>

        <div className="tabs">
          {/* Ini cara menulis komentar di dalam JSX. */}
          {/* Tiap tombol: kalau tab ini sedang aktif, beri class "active"
              (agar warnanya berbeda); kalau tidak, class kosong.
              onClick = kerjakan fungsi ini saat tombol diklik. */}
          <button className={tab === "monitor" ? "active" : ""} onClick={() => setTab("monitor")}>
            Monitor
          </button>
          <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
            Kalibrasi
          </button>
          <button className={tab === "dataset" ? "active" : ""} onClick={() => setTab("dataset")}>
            Dataset
          </button>
          <button className={tab === "annotate" ? "active" : ""} onClick={() => setTab("annotate")}>
            Anotasi
          </button>
          <button className={tab === "training" ? "active" : ""} onClick={() => setTab("training")}>
            Training
          </button>
        </div>

        {/* Elemen kosong sebagai pengisi ruang, agar tombol-tombol berikutnya
            terdorong ke sisi kanan layar. */}
        <div className="spacer" />

        <div className="conn">
          {/* Bulatan indikator: hijau ("ok") kalau terhubung, merah ("bad") kalau tidak. */}
          <span className={"dot " + (online ? "ok" : "bad")} />
          {online ? "Terhubung" : "Menghubungkan..."}
        </div>

        <button
          className="btn sm"
          // Tanda ! membalik nilainya: kalau sekarang manual, klik ini
          // mengubahnya jadi auto, dan sebaliknya.
          onClick={() => setMode(!manual)}
          // title = tulisan bantuan yang muncul saat kursor diarahkan ke tombol.
          title="Mode manual menahan otomatis untuk kalibrasi"
        >
          Mode: {manual ? "MANUAL" : "AUTO"}
        </button>

        {/* Menampilkan tombol yang BERBEDA tergantung kondisi:
            sedang E-STOP -> tombol untuk melepasnya;
            normal        -> tombol merah E-STOP. */}
        {isEstop ? (
          <button className="btn primary" onClick={clearEstop}>
            Lepas E-STOP
          </button>
        ) : (
          <button className="btn estop" onClick={estop}>
            ■ E-STOP
          </button>
        )}
      </div>

      {/* Pola "syarat && <Komponen />" berarti: tampilkan komponen ini HANYA
          kalau syaratnya benar. Inilah cara berpindah halaman tanpa memuat
          ulang browser. */}
      {/* status={status} adalah "props": mengirim data dari induk ke anak. */}
      {tab === "monitor" && <Monitor status={status} />}
      {tab === "settings" && <Settings status={status} />}
      {tab === "dataset" && (
        <Dataset
          // Mengirim FUNGSI sebagai props. Halaman Dataset akan memanggilnya
          // saat tombol "Anotasi" diklik pada sebuah foto — lalu induk inilah
          // yang mencatat foto mana yang dipilih dan berpindah tab.
          onAnnotate={(name) => {
            setAnnotateImg(name);
            setTab("annotate");
          }}
        />
      )}
      {tab === "annotate" && <Annotate initial={annotateImg} />}
      {tab === "training" && <Training />}
    </div>
  );
}
