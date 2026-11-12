# RakshaMarg: pre-dispatch route risk decisions for fleet dispatchers

**Team PLACER** · Shantanu Singh · IIT (BHU) Varanasi · Netradyne Campus Innovation Challenge 2026 (Prototype Phase)

- **Live demo:** https://shantanusinghmet22-cloud.github.io/rakshamarg/
- **Demo video:** https://youtu.be/Tr2X6_HXE9Y
- **Full source code, tests and documentation:** [`rakshamarg/`](rakshamarg/). Start with [`rakshamarg/README.md`](rakshamarg/README.md).

The top-level `index.html` is the self-contained dispatcher console (the same file as `rakshamarg/docs/index.html`).

## Run locally
```bash
cd rakshamarg
pip install -r requirements.txt
uvicorn api:app --port 8000          # API docs at http://localhost:8000/docs
python tests/test_pipeline.py && python tests/test_api.py
node tests/test_engine.cjs && node tests/test_adapters.cjs
```

All fleet results are measured on simulated data; the real-roads mode (NH-19 around Prayagraj) is experimental. Licence: MIT.
