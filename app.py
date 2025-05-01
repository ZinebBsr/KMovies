from flask import Flask, render_template, request
import sqlite3
import pickle
import os

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PICKLE_PATH = os.path.join(BASE_DIR, "clusters.pkl")
DB_PATH = os.path.join(BASE_DIR, "moviesdatabase.db")

# Chargement du fichier clusters.pkl
try:
    with open(PICKLE_PATH, "rb") as f:
        donnees = pickle.load(f)
        cluster_data = donnees["clusters"]  # Liste de listes de tconst
        noms_clusters = donnees["noms"]  # Liste de noms, même ordre
except FileNotFoundError:
    print("Erreur : Le fichier clusters.pkl n'a pas été trouvé. Vérifiez le chemin.")
    cluster_data = []
    noms_clusters = []
except Exception as e:
    print(f"Erreur lors du chargement de clusters.pkl : {e}")
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
        print(f"Erreur lors de la connexion à la base de données : {e}")
        return None

# Route pour la page d'accueil
@app.route("/")
def index():
    conn = get_db_connection()
    if conn is None:
        print("Échec de la connexion à la base de données")
        return "Erreur de connexion à la base de données", 500

    # Films récents (10 films les plus récents, triés par note)
    query_recent = """
    SELECT tconst, primaryTitle, averageRating, poster, startYear
    FROM movies_with_directors 
    WHERE startYear IS NOT NULL AND averageRating IS NOT NULL
    ORDER BY startYear DESC, averageRating DESC 
    LIMIT 20
    """

    # Films populaires (basés sur numVotes)
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
        print(f"Erreur lors de l'exécution des requêtes : {e}")
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
        print(f"Erreur lors de l'exécution de la requête : {e}")
        movie = None
    finally:
        conn.close()

    if movie is None:
        return "Film non trouvé", 404

    return render_template("film_detail.html", movie=movie)

@app.route("/clusters")
def clusters():
    clusters = [{"id": cluster_id, "name": cluster_name} for cluster_id, cluster_name in cluster_names.items()]
    total_clusters = len(clusters)  # Nombre total de clusters
    return render_template("clusters.html", clusters=clusters, total_clusters=total_clusters)

# Route pour un cluster spécifique
@app.route("/cluster/<int:cluster_id>")
def cluster_detail(cluster_id):
    if cluster_id not in cluster_names:
        return "Cluster non trouvé", 404

    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    # Récupérer les films du cluster
    tconsts = cluster_data[cluster_id]
    if not tconsts:
        conn.close()
        return render_template("cluster_detail.html", cluster_name=cluster_names[cluster_id], movies=[])

    # Créer une chaîne pour la requête SQL avec des placeholders
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
        print(f"Erreur lors de l'exécution de la requête : {e}")
        movies = []
    finally:
        conn.close()

    return render_template("cluster_detail.html", cluster_name=cluster_names[cluster_id], movies=movies)

# Route pour la page de recommandations
@app.route("/recommendations", methods=["GET", "POST"])
def recommendations():
    conn = get_db_connection()
    if conn is None:
        return "Erreur de connexion à la base de données", 500

    # Récupérer tous les films pour la liste déroulante
    query_all_movies = """
    SELECT tconst, primaryTitle
    FROM movies_with_directors 
    WHERE averageRating IS NOT NULL 
    ORDER BY primaryTitle ASC
    """
    try:
        all_movies = conn.execute(query_all_movies).fetchall()
    except sqlite3.Error as e:
        print(f"Erreur lors de l'exécution de la requête : {e}")
        all_movies = []
    
    recommended_movies = []
    cluster_name = None
    selected_movie_title = None

    if request.method == "POST":
        selected_tconst = request.form.get("movie")
        if selected_tconst:
            # Récupérer le titre du film sélectionné
            query_selected_movie = """
            SELECT primaryTitle
            FROM movies_with_directors 
            WHERE tconst = ?
            """
            try:
                selected_movie = conn.execute(query_selected_movie, (selected_tconst,)).fetchone()
                selected_movie_title = selected_movie["primaryTitle"] if selected_movie else None
            except sqlite3.Error as e:
                print(f"Erreur lors de l'exécution de la requête : {e}")
                selected_movie_title = None

            # Trouver le cluster auquel appartient le film sélectionné
            cluster_id = None
            for idx, cluster in enumerate(cluster_data):
                if selected_tconst in cluster:
                    cluster_id = idx
                    cluster_name = cluster_names[cluster_id]
                    break
            
            if cluster_id is not None:
                # Récupérer les films du cluster (exclure le film sélectionné)
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
                        print(f"Erreur lors de l'exécution de la requête : {e}")
                        recommended_movies = []

    conn.close()
    return render_template("recommendations.html", all_movies=all_movies, recommended_movies=recommended_movies, cluster_name=cluster_name, selected_movie_title=selected_movie_title)

# Route pour la page About
@app.route("/about")
def about():
    return render_template("about.html")

# Lancer le serveur Flask (pour tests locaux uniquement)
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
