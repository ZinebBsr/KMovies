from flask import Flask, render_template, request
import sqlite3
import pickle
import os
import subprocess

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PICKLE_PATH = os.path.join(BASE_DIR, "clusters.pkl")
DB_PATH = os.path.join(BASE_DIR, "moviesdatabase.db")

# Fetch and recombine database parts at startup
if not os.path.exists(DB_PATH):
    # List of Google Drive direct download links for each part
    download_links = [
        "https://drive.google.com/uc?export=download&id=1urd03BYonjnZKR-xmSdUEIoR2NqLIBaU",  # partaa
        "https://drive.google.com/uc?export=download&id=1NdLQcMouKL9fmiI7YIwnYvB_opLJVGTV",  # partab
        "https://drive.google.com/uc?export=download&id=1zTzeBygoN235ze8UU-oz8SmQ2tLTx9NZ",  # partac
        "https://drive.google.com/uc?export=download&id=13GO_K0V8pdPz5dJ5pb_-l2JfwmdWLJl-",  # partad
        "https://drive.google.com/uc?export=download&id=1T13tqRz90_YVxeqcvBljCVnK7qIvJUt4",  # partae
        "https://drive.google.com/uc?export=download&id=1r_fYCfWl2DpyeWu-0Av3AWYDzu0T7cPH",  # partaf
        "https://drive.google.com/uc?export=download&id=1spXBzV5gqX8tq176NAFP2yr3B2yixiQ6",  # partag
        "https://drive.google.com/uc?export=download&id=1JBaC24kpjrAIwCOx_u0JkeLfPjgmrnVP",  # partah
        "https://drive.google.com/uc?export=download&id=1ClSGEICy7pWiOROnnWt_uaP3NQ7B0LBk",  # partai
        "https://drive.google.com/uc?export=download&id=1lDA9Fx6fvCB46EeYwojRbi8XiEswViR_",  # partaj
        "https://drive.google.com/uc?export=download&id=1SE3564Rr66zide0MFry6nv_jppRTHODK",  # partak
        "https://drive.google.com/uc?export=download&id=1LdbtFOtIH7aB5yZrBDSxHHvc1n9aPu70",  # partal
        "https://drive.google.com/uc?export=download&id=1x_stJT-vXo76mHQEn1WeWd-LN1RZVwyt",  # partam
        "https://drive.google.com/uc?export=download&id=1O_Xlz541r0C2IyLlMnUhaZSQgO_ephno"   # partan
    ]

    # Download each part
    for i, link in enumerate(download_links):
        part_name = f"parta{i:02d}"  # e.g., partaa, partab, ..., partan
        try:
            subprocess.run(["wget", "-O", part_name, link], check=True)
        except subprocess.CalledProcessError as e:
            app.logger.error(f"Failed to download {part_name}: {e}")
            raise

    # Recombine parts into moviesdatabase.db
    try:
        with open(DB_PATH, "wb") as outfile:
            for part_name in [f"parta{i:02d}" for i in range(len(download_links))]:
                with open(part_name, "rb") as infile:
                    outfile.write(infile.read())
                os.remove(part_name)  # Clean up temporary files
    except Exception as e:
        app.logger.error(f"Error recombining database: {e}")
        raise

# Chargement du fichier clusters.pkl
try:
    with open(PICKLE_PATH, "rb") as f:
        donnees = pickle.load(f)
        cluster_data = donnees["clusters"]  # Liste de listes de tconst
        noms_clusters = donnees["noms"]  # Liste de noms, même ordre
except FileNotFoundError:
    app.logger.error("Erreur : Le fichier clusters.pkl n'a pas été trouvé. Vérifiez le chemin.")
    cluster_data = []
    noms_clusters = []
except Exception as e:
    app.logger.error(f"Erreur lors du chargement de clusters.pkl : {e}")
    cluster_data = []
    noms_clusters = []

# Construction d'un dictionnaire : id → nom
cluster_names = {i: noms_clusters[i] for i in range(len(noms_clusters))}

# Connexion à la base de données SQLite
def get_db_connection():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de la connexion à la base de données : {e}")
        return None

# Route pour la page d'accueil
@app.route("/")
def index():
    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    query_recent = """
    SELECT tconst, primaryTitle, averageRating, poster, startYear
    FROM movies_with_directors 
    WHERE startYear IS NOT NULL AND averageRating IS NOT NULL
    ORDER BY startYear DESC, averageRating DESC 
    LIMIT 20
    """

    query_popular = """
    SELECT tconst, primaryTitle, averageRating, poster
    FROM movies_with_directors 
    WHERE numVotes IS NOT NULL 
    ORDER BY numVotes DESC 
    LIMIT 20
    """

    try:
        recent_movies = conn.execute(query_recent).fetchall()
        popular_movies = conn.execute(query_popular).fetchall()
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de l'exécution des requêtes : {e}")
        recent_movies = []
        popular_movies = []
    finally:
        conn.close()

    return render_template("index.html", recent_movies=recent_movies, popular_movies=popular_movies)

# Route pour les détails d'un film
@app.route("/film/<tconst>")
def film_detail(tconst):
    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    query = """
    SELECT tconst, primaryTitle, averageRating, genres, country, plot, directorName, poster
    FROM movies_with_directors 
    WHERE tconst = ?
    """
    try:
        movie = conn.execute(query, (tconst,)).fetchone()
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de l'exécution de la requête : {e}")
        movie = None
    finally:
        conn.close()

    if movie is None:
        return "Film non trouvé", 404

    return render_template("film_detail.html", movie=movie)

@app.route("/clusters")
def clusters():
    clusters = [{"id": cluster_id, "name": cluster_name} for cluster_id, cluster_name in cluster_names.items()]
    total_clusters = len(clusters)
    return render_template("clusters.html", clusters=clusters, total_clusters=total_clusters)

@app.route("/cluster/<int:cluster_id>")
def cluster_detail(cluster_id):
    if cluster_id not in cluster_names:
        return "Cluster non trouvé", 404

    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    tconsts = cluster_data[cluster_id]
    if not tconsts:
        conn.close()
        return render_template("cluster_detail.html", cluster_name=cluster_names[cluster_id], movies=[])

    placeholders = ",".join("?" for _ in tconsts)
    query = f"""
    SELECT tconst, primaryTitle, averageRating, poster
    FROM movies_with_directors 
    WHERE tconst IN ({placeholders})
    ORDER BY numVotes DESC
    """
    try:
        movies = conn.execute(query, tconsts).fetchall()
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de l'exécution de la requête : {e}")
        movies = []
    finally:
        conn.close()

    return render_template("cluster_detail.html", cluster_name=cluster_names[cluster_id], movies=movies)

@app.route("/recommendations", methods=["GET", "POST"])
def recommendations():
    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    query_all_movies = """
    SELECT tconst, primaryTitle
    FROM movies_with_directors 
    WHERE averageRating IS NOT NULL 
    ORDER BY primaryTitle ASC
    """
    try:
        all_movies = conn.execute(query_all_movies).fetchall()
    except sqlite3.Error as e:
        app.logger.error(f"Erreur lors de l'exécution de la requête : {e}")
        all_movies = []

    recommended_movies = []
    cluster_name = None
    selected_movie_title = None

    if request.method == "POST":
        selected_tconst = request.form.get("movie")
        if selected_tconst:
            query_selected_movie = """
            SELECT primaryTitle
            FROM movies_with_directors 
            WHERE tconst = ?
            """
            try:
                selected_movie = conn.execute(query_selected_movie, (selected_tconst,)).fetchone()
                selected_movie_title = selected_movie["primaryTitle"] if selected_movie else None
            except sqlite3.Error as e:
                app.logger.error(f"Erreur lors de l'exécution de la requête : {e}")
                selected_movie_title = None

            cluster_id = None
            for idx, cluster in enumerate(cluster_data):
                if selected_tconst in cluster:
                    cluster_id = idx
                    cluster_name = cluster_names[cluster_id]
                    break
            
            if cluster_id is not None:
                tconsts = [tconst for tconst in cluster_data[cluster_id] if tconst != selected_tconst]
                if tconsts:
                    placeholders = ",".join("?" for _ in tconsts)
                    query_recommendations = f"""
                    SELECT tconst, primaryTitle, averageRating, poster
                    FROM movies_with_directors 
                    WHERE tconst IN ({placeholders})
                    ORDER BY numVotes DESC
                    LIMIT 40
                    """
                    try:
                        recommended_movies = conn.execute(query_recommendations, tconsts).fetchall()
                    except sqlite3.Error as e:
                        app.logger.error(f"Erreur lors de l'exécution de la requête : {e}")
                        recommended_movies = []

    conn.close()
    return render_template("recommendations.html", all_movies=all_movies, recommended_movies=recommended_movies, cluster_name=cluster_name, selected_movie_title=selected_movie_title)

@app.route("/about")
def about():
    return render_template("about.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
