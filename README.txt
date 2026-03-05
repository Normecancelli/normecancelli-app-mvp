NORMECANCELLI – ASSISTENTE NORMATIVE (MVP)

Cos’è:
- Una mini-app (Streamlit) che fa domande a “wizard”
- Salva i fatti (facts) e applica regole (results) definite in rules.yaml
- Produce un report e lo fa scaricare in PDF

COME SI AVVIA (Mac/Windows):
1) Installa Python 3.10+ (se non ce l’hai già)
2) Da terminale:
   pip install -r requirements.txt
3) Avvia:
   streamlit run app.py

DOVE SI MODIFICA LA LOGICA:
- Apri rules.yaml
- Cambia domande, aggiungi nodi, aggiungi regole in results

Nota importante:
Questo è un prototipo. La potenza vera arriva quando:
- inseriamo la tua “logica NormeCancelli”
- aggiungiamo casi d’uso (condominio, industria, barriere, portoni, ecc.)
- aggiungiamo output più operativi: checklist “da campo”, modelli documentali, riferimenti puntuali.
DEPLOY RAPIDO SU RENDER (consigliato per MVP)
1) Carica questi file su un repo GitHub.
2) Su Render: New -> Blueprint -> seleziona il repo (usa render.yaml).
3) Quando è online, in Render -> Settings -> Custom Domains -> aggiungi app.growset.it
4) Render ti dirà che record DNS mettere (di solito CNAME).
   Su Aruba: elimina il record A "app" e crea il CNAME "app" con il valore indicato da Render.

In alternativa puoi usare Dockerfile su qualsiasi host compatibile Docker.
