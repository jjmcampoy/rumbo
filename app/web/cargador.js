/* Carga los scripts con un sello temporal para que, al recargar despues de
   actualizar, el navegador no sirva los datos viejos de su cache.
   async=false conserva el orden de ejecucion.
   Va en un archivo aparte (no en linea) para poder usar una CSP estricta. */
(function () {
  var sello = location.protocol === "file:" ? "" : "?v=" + Date.now();
  ["datos.js", "canal.js", "graficos.js", "app.js", "editor.js"].forEach(function (archivo) {
    var s = document.createElement("script");
    s.src = archivo + sello;
    s.async = false;
    document.body.appendChild(s);
  });
})();
