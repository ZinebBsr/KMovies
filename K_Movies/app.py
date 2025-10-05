from flask import Flask, render_template, request
import sqlite3
import pickle
import os
import requests
import time

app = Flask(__name__)

# ---- CONFIG ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "moviesdatabase.db")       # ta DB SQLite
PICKLE_PATH = os.path.join(BASE_DIR, "clusters.pkl")        # tes clusters
OMDB_API_KEY = "3fd7a9f1"                                   # ta clé OMDb
TMDB_API_KEY = "b0547ae541d517b7e3752c5a20999869"          # ta clé TMDb
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# Cache pour limiter les appels externes (clé -> (timestamp, value))
_cache = {}
CACHE_TTL = 10 * 60  # 10 minutes

# ---- Chargement clusters.pkl ----
try:
    with open(PICKLE_PATH, "rb") as f:
        donnees = pickle.load(f)
        cluster_data = donnees.get("clusters", [])
        noms_clusters = donnees.get("noms", [])
except FileNotFoundError:
    app.logger.warning("clusters.pkl non trouvé — cluster_data vide.")
    cluster_data, noms_clusters = [], []
except Exception as e:
    app.logger.error(f"Erreur chargement clusters.pkl : {e}")
    cluster_data, noms_clusters = [], []

cluster_names = {i: noms_clusters[i] for i in range(len(noms_clusters))}

# ---- Helpers DB ----
def get_db_connection():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        app.logger.error(f"Erreur DB: {e}")
        return None

# ---- Helpers TMDb / OMDb ----
def fetch_json(url, params=None, timeout=6):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        app.logger.error(f"Erreur requete externe {url} : {e}")
        return None

def get_recent_movies_from_tmdb(page=1):
    """Récupère les films now_playing depuis TMDb (cached)."""
    cache_key = f"tmdb_now_playing_p{page}"
    now = time.time()
    if cache_key in _cache:
        ts, value = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return value

    url = "https://api.themoviedb.org/3/movie/now_playing"
    params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": page}
    data = fetch_json(url, params)
    movies = []
    if data and data.get("results"):
        for item in data["results"]:
            poster = TMDB_IMAGE_BASE + item["poster_path"] if item.get("poster_path") else "/static/image/no_poster.png"
            
            # récupération des pays pour TMDb
            countries = []
            if item.get("production_countries"):
                countries = [c["iso_3166_1"] for c in item["production_countries"]]
            movies.append({
                "tconst": str(item.get("id")),
                "primaryTitle": item.get("title"),
                "poster": poster,
                "averageRating": round(item.get("vote_average", 0), 1),  # arrondi 1 décimale
                "release_date": item.get("release_date"),
                "country": ", ".join(countries) if countries else "N/A"
            })
    _cache[cache_key] = (now, movies)
    return movies

def get_movie_from_tmdb(tmdb_id):
    """Récupère détails TMDb (ajoute external_ids pour voir imdb_id si voulu)."""
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    params = {"api_key": TMDB_API_KEY, "append_to_response": "external_ids,production_countries"}
    data = fetch_json(url, params)
    if not data:
        return None
    poster = TMDB_IMAGE_BASE + data["poster_path"] if data.get("poster_path") else "/static/image/no_poster.png"
    
    countries = data.get("production_countries", [])
    country_str = ", ".join([c["iso_3166_1"] for c in countries]) if countries else "N/A"
    
    return {
        "primaryTitle": data.get("title"),
        "startYear": data.get("release_date"),
        "runtimeMinutes": data.get("runtime"),
        "genres": ", ".join(g["name"] for g in data.get("genres", [])),
        "averageRating": round(data.get("vote_average", 0), 1),
        "directorName": None,   # peut utiliser /credits si nécessaire
        "plot": data.get("overview"),
        "poster": poster,
        "country": country_str,
        "imdb_id": data.get("external_ids", {}).get("imdb_id"),
        "tmdb_id": str(tmdb_id),
    }

def get_movie_from_omdb_by_imdb(imdb_id):
    url = "http://www.omdbapi.com/"
    params = {"apikey": OMDB_API_KEY, "i": imdb_id, "plot": "full"}
    data = fetch_json(url, params)
    if not data or data.get("Response") != "True":
        return None
    poster = data.get("Poster") if data.get("Poster") and data.get("Poster") != "N/A" else "/static/image/no_poster.png"
    return {
        "primaryTitle": data.get("Title"),
        "startYear": data.get("Year"),
        "runtimeMinutes": data.get("Runtime"),
        "genres": data.get("Genre"),
        "averageRating": round(float(data.get("imdbRating", 0)), 1),
        "directorName": data.get("Director"),
        "plot": data.get("Plot"),
        "poster": poster,
        "country": data.get("Country") or "N/A",
        "imdb_id": data.get("imdbID"),
    }

# ---- ROUTES ----
@app.route("/")
def index():
    # films récents depuis TMDb
    recent_movies = get_recent_movies_from_tmdb(page=1)

    # films populaires depuis DB
    conn = get_db_connection()
    popular_movies = []
    if conn:
        try:
            query_popular = """
            SELECT tconst, primaryTitle, averageRating, poster, country
            FROM movies_with_directors
            WHERE numVotes IS NOT NULL
            ORDER BY numVotes DESC
            LIMIT 20
            """
            rows = conn.execute(query_popular).fetchall()
            for r in rows:
                popular_movies.append({
                    "tconst": r["tconst"],
                    "primaryTitle": r["primaryTitle"],
                    "averageRating": round(float(r["averageRating"]), 1) if r["averageRating"] else "N/A",
                    "poster": r["poster"] or "/static/image/no_poster.png",
                    "country": r["country"] or "N/A"
                })
        except sqlite3.Error as e:
            app.logger.error(f"Erreur SQL popular: {e}")
        finally:
            conn.close()
    else:
        return "Erreur de connexion à la base de données", 500

    return render_template("index.html", recent_movies=recent_movies, popular_movies=popular_movies)

@app.route("/film/<tconst>")
def film_detail(tconst):
    """
    tconst peut être :
      - IMDb id (tt...) -> DB puis OMDb
      - TMDb id (numérique) -> TMDb
    """
    conn = get_db_connection()
    movie = None

    if conn:
        try:
            q = """
            SELECT tconst, primaryTitle, startYear, runtimeMinutes, genres, averageRating, directorName, plot, poster, country
            FROM movies_with_directors
            WHERE tconst = ?
            """
            row = conn.execute(q, (tconst,)).fetchone()
            if row:
                movie = {k: row[k] for k in row.keys()}
                movie["averageRating"] = round(float(movie["averageRating"]), 1) if movie.get("averageRating") else "N/A"
                movie["country"] = movie.get("country") or "N/A"
        except sqlite3.Error as e:
            app.logger.error(f"Erreur SQL film_detail DB: {e}")
        finally:
            conn.close()

    if not movie:
        if tconst.startswith("tt"):  # IMDb -> OMDb
            movie = get_movie_from_omdb_by_imdb(tconst)
            if movie:
                movie["tconst"] = movie.get("imdb_id")
        elif tconst.isdigit():  # TMDb
            movie = get_movie_from_tmdb(tconst)
            if movie:
                movie["tconst"] = movie.get("tmdb_id")
        else:
            return "Film non trouvé", 404

    if not movie:
        return "Film non trouvé", 404

    return render_template("film_detail.html", movie=movie)

@app.route("/clusters")
def clusters():
    clusters = [{"id": cid, "name": cname} for cid, cname in cluster_names.items()]
    return render_template("clusters.html", clusters=clusters, total_clusters=len(clusters))

@app.route("/cluster/<int:cluster_id>")
def cluster_detail(cluster_id):
    if cluster_id not in cluster_names:
        return "Cluster non trouvé", 404

    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    tconsts = cluster_data[cluster_id] if cluster_id < len(cluster_data) else []
    if not tconsts:
        conn.close()
        return render_template("cluster_detail.html", cluster_name=cluster_names[cluster_id], movies=[])

    placeholders = ",".join("?" for _ in tconsts)
    query = f"""
    SELECT tconst, primaryTitle, averageRating, poster, country
    FROM movies_with_directors 
    WHERE tconst IN ({placeholders})
    ORDER BY numVotes DESC
    """
    try:
        movies = conn.execute(query, tconsts).fetchall()
        movies = [
            {
                "tconst": m["tconst"],
                "primaryTitle": m["primaryTitle"],
                "averageRating": round(float(m["averageRating"]), 1) if m.get("averageRating") else "N/A",
                "poster": m["poster"] or "/static/image/no_poster.png",
                "country": m["country"] or "N/A"
            }
            for m in movies
        ]
    except sqlite3.Error as e:
        app.logger.error(f"Erreur SQL cluster_detail: {e}")
        movies = []
    finally:
        conn.close()

    return render_template("cluster_detail.html", cluster_name=cluster_names[cluster_id], movies=movies)

@app.route("/recommendations", methods=["GET", "POST"])
def recommendations():
    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    all_movies = []
    try:
        q = "SELECT tconst, primaryTitle FROM movies_with_directors WHERE averageRating IS NOT NULL ORDER BY primaryTitle ASC"
        rows = conn.execute(q).fetchall()
        all_movies = [{"tconst": r["tconst"], "primaryTitle": r["primaryTitle"]} for r in rows]
    except sqlite3.Error as e:
        app.logger.error(f"Erreur SQL recommendations: {e}")

    recommended_movies = []
    cluster_name = None
    selected_movie_title = None

    if request.method == "POST":
        selected_tconst = request.form.get("movie")
        if selected_tconst:
            selected_movie = next((m for m in all_movies if m["tconst"] == selected_tconst), None)
            selected_movie_title = selected_movie["primaryTitle"] if selected_movie else None

            cluster_id = next((idx for idx, cl in enumerate(cluster_data) if selected_tconst in cl), None)
            if cluster_id is not None:
                cluster_name = cluster_names.get(cluster_id)
                tconsts = [t for t in cluster_data[cluster_id] if t != selected_tconst]
                if tconsts:
                    placeholders = ",".join("?" for _ in tconsts)
                    q2 = f"SELECT tconst, primaryTitle, averageRating, poster, country FROM movies_with_directors WHERE tconst IN ({placeholders}) ORDER BY numVotes DESC LIMIT 40"
                    try:
                        rows = conn.execute(q2, tconsts).fetchall()
                        recommended_movies = [
                            {
                                "tconst": r["tconst"],
                                "primaryTitle": r["primaryTitle"],
                                "averageRating": round(float(r["averageRating"]), 1) if r.get("averageRating") else "N/A",
                                "poster": r["poster"] or "/static/image/no_poster.png",
                                "country": r["country"] or "N/A"
                            }
                            for r in rows
                        ]
                    except sqlite3.Error as e:
                        app.logger.error(f"Erreur SQL recommendations fetch: {e}")
    conn.close()
    return render_template("recommendations.html", all_movies=all_movies, recommended_movies=recommended_movies, cluster_name=cluster_name, selected_movie_title=selected_movie_title)

@app.route("/about")
def about():
    return render_template("about.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
