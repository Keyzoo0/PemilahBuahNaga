// CATATAN UNTUK PEMULA:
// Ini file TITIK MASUK aplikasi web — baris pertama yang dijalankan browser.
// Isinya sangat pendek karena tugasnya cuma satu: menempelkan aplikasi React
// ke dalam halaman HTML.

import React from "react";
// createRoot adalah cara React versi 18 ke atas untuk memulai aplikasi.
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
// Mengimpor file CSS agar tampilannya ikut dimuat. Ini khas Vite/React:
// file gaya pun bisa di-import seperti kode.
import "./styles.css";

// Dibaca dari dalam ke luar:
//   document.getElementById("root") -> cari elemen <div id="root"> di index.html
//   createRoot(...)                 -> jadikan elemen itu wadah aplikasi React
//   .render(<App />)                -> gambar komponen App ke dalam wadah tersebut
// Mulai dari sini, seluruh isi halaman dikendalikan React.
createRoot(document.getElementById("root")).render(<App />);
