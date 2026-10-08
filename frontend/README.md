# Study Buddy : frontend

Interface React + TypeScript (Vite) du backend situé dans `../backend`.

## Lancer en local

1. Démarrer le backend (port 8000) depuis `../backend` (voir le README à la racine du dépôt).
2. Démarrer le frontend depuis ce dossier :

```bash
npm install
npm run dev
```

3. Ouvrir http://localhost:5173.

Les appels vers `/api/*` sont redirigés vers `http://localhost:8000` par le proxy de Vite (`vite.config.ts`), donc pas besoin de configurer CORS côté backend. Le navigateur ne parle qu'au backend : la clé RodiumAI n'est jamais dans le code du frontend.

## Endpoints utilisés

| Méthode | Route | Usage |
| --- | --- | --- |
| `GET` | `/models` | Liste des modèles autorisés (sélecteur) |
| `GET` | `/conversations` | Historique des conversations (barre latérale) |
| `POST` | `/conversations` | Bouton « Nouvelle conversation » |
| `GET` | `/conversations/{id}/messages` | Messages d'une conversation |
| `POST` | `/conversations/{id}/notes` | Ajout d'une note personnelle (rôle `note`) |
| `POST` | `/chat` | Envoi d'un message, réponse en streaming (lue avec `fetch` + `response.body.getReader()` dans `src/api.ts`) |
