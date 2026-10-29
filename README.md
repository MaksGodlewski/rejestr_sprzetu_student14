# Rejestr wypożyczania sprzętu komputerowego (Student14)

Aplikacja webowa do ewidencji wypożyczeń laptopów, projektorów i innych urządzeń.
Projekt końcowy: Specjalizacja DevSecOps – kontenery i automatyzacja (Docker + GitHub).

## Funkcjonalności
- dodawanie sprzętu do katalogu (nazwa, kategoria, numer inwentarzowy),
- rejestrowanie osoby wypożyczającej (imię i nazwisko, kontakt),
- zapisywanie daty wypożyczenia, planowanego terminu i faktycznego zwrotu,
- status sprzętu: dostępny / wypożyczony (z filtrem w katalogu),
- lista aktywnych wypożyczeń (z oznaczeniem „po terminie”) i historia zwrotów.

## Architektura

```
 przeglądarka ──:8000──▶ [ web: Flask + gunicorn ] ──sieć backend (internal)──▶ [ db: PostgreSQL 16 ]
                              (sieć frontend)                                         │
                                                                                volume: pgdata
```

| Element | Rozwiązanie |
|---|---|
| Kontener `web` | własny `Dockerfile` (python:3.12-slim, użytkownik nie-root, HEALTHCHECK) |
| Kontener `db` | `postgres:16-alpine`, healthcheck `pg_isready` |
| Sieci | `frontend` (publikacja portu 8000) i `backend` (`internal: true` – baza odizolowana) |
| Dane | nazwany wolumen `pgdata` – dane przetrwają `docker compose down` |
| Kolejność startu | `depends_on: condition: service_healthy` |
| Sekrety | hasła w `.env` (poza repozytorium, w repo tylko `.env.example`) |
| Opcjonalnie | `adminer` (profil `tools`) do podglądu bazy |

## Uruchomienie

```bash
git clone <adres-repozytorium> && cd <katalog>
cp .env.example .env        # ustaw własne hasło w POSTGRES_PASSWORD
docker compose up -d --build
```

Aplikacja: http://localhost:8000 | kontrola: http://localhost:8000/health

Podgląd bazy (opcjonalnie): `docker compose --profile tools up -d` → http://localhost:8080
(system: PostgreSQL, serwer: `db`, dane z `.env`).

Zatrzymanie: `docker compose down` (dane zostają) lub `docker compose down -v` (usuwa dane).

## Testy

Testy wymagają PostgreSQL. Lokalnie:

```bash
docker run -d --name testdb -p 5432:5432 -e POSTGRES_DB=rejestr \
  -e POSTGRES_USER=rejestr -e POSTGRES_PASSWORD=rejestr postgres:16-alpine
pip install -r requirements-dev.txt
flake8 . && pytest -v
docker rm -f testdb
```

## Pipeline CI/CD (`.github/workflows/ci.yml`)

Uruchamia się przy push na `main`, pull requestach i ręcznie.

1. **lint-test** – `flake8` oraz `pytest` na usłudze PostgreSQL.
2. **docker** – Hadolint (kontrola Dockerfile), `docker compose config`, budowanie obrazu,
   start stosu (`up --wait`), test dymny przez `curl`, test trwałości danych po restarcie bazy,
   a na gałęzi `main` publikacja obrazu do GitHub Container Registry (`ghcr.io`).

## Scenariusz testu ręcznego (do dokumentacji)

1. `docker compose up -d --build`, `docker compose ps` – oba kontenery `healthy`.
2. Katalog: dodaj „Dell Latitude 5420”, kategoria laptop, nr `LAP-001`.
3. Wypożyczenia: wypożycz go osobie „Jan Kowalski” z terminem zwrotu – status zmienia się na „wypożyczony”.
4. Spróbuj wypożyczyć ten sam sprzęt ponownie – brak go na liście dostępnych.
5. `docker compose down && docker compose up -d` – dane nadal są (wolumen).
6. Kliknij „Zwrot” – sprzęt wraca jako „dostępny”, wpis trafia do historii.
7. `docker network inspect <projekt>_backend` – sieć `Internal: true`.

## Ograniczenia
Brak logowania i ochrony CSRF – to prosta aplikacja do pracy w sieci zaufanej / demonstracji.
