"""Modulo Web: studio del front-end di un sito per costruirne una propria versione.

Cosa fa: scarica solo ciò che un browser riceve già (HTML, CSS e JavaScript
pubblici dello stesso sito), ne ricava una mappa strutturale (sezioni,
componenti, stili, librerie, layout) e la fa spiegare al modello. Poi genera
uno scheletro HTML/CSS pulito, con testi e immagini segnaposto, che l'utente
riempie con i propri contenuti.

Cosa NON fa, per scelta e non per limite tecnico:
- non clona un sito per ripubblicarlo: testi, immagini, loghi e marchi
  restano dei titolari e non vengono copiati nello scheletro;
- non scarica immagini, font o video;
- non aggira login, paywall o misure anti-scraping, e rispetta robots.txt
  (un 401/403/429 ferma la raccolta).

Lo stesso design visivo di un sito può essere tutelato (diritto d'autore,
marchi, concorrenza sleale): lo scheletro è un punto di partenza da
reinterpretare, non una copia.
"""
