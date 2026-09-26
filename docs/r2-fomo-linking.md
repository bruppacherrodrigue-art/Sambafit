# R2 — lier un profil Fomo à un wallet public

Au 26 septembre 2026, **zéro** des wallets de la cohorte R2 a une attribution Fomo prouvée. Ils restent `onchain_unattributed`. Le lien `https://fomo.family/r/nobrainflip` est une piste de parrainage seulement : il ne démontre ni l'identité d'un profil, ni une adresse Solana. Aucun classement Fomo de « meilleurs wallets sur le long terme » n'est produit sans identités et historique vérifiables.

## Voies officielles effectivement examinées

| Méthode consultée | Constat observé | Ce qui manque pour la liaison |
|---|---|---|
| [Guide officiel de navigation Fomo](https://fomo.family/blog/learn/navigating-your-fomo-app) et [fonctions sociales](https://fomo.family/blog/learn/leveraging-fomos-social-features) | Profils, découvertes et contexte social sont décrits. | Aucun contrat public profil → adresse vérifiable n'est fourni par ces pages. |
| [Guide officiel dépôts/retraits](https://fomo.family/blog/learn/a-guide-to-deposits-and-withdrawals) et [architecture de wallet](https://fomo.family/blog/learn/fomo-security-wallet-architecture) | Le flux du compte propre peut afficher une adresse publique de dépôt. | Une adresse de dépôt du compte propre ne prouve pas automatiquement qu'un profil public précis en est propriétaire ; il faut une preuve reliant les deux. |
| [Annonce Fomo Web](https://fomo.family/blog/announcing-fomo-web) | L'accès Web est décrit publiquement. | Aucun export officiel de mapping des profils publics vers leurs adresses n'a été établi dans les ressources examinées. Cela ne prouve pas qu'aucune voie autorisée existe dans une session. |
| Lien `https://fomo.family/r/nobrainflip` | URL de parrainage fournie dans la conversation ; ouverture documentaire non exploitable pour une adresse. | Ce lien n'est jamais accepté comme référence de preuve d'un profil/wallet. |

Nous n'avons **pas** ouvert une session Fomo utilisateur, ni observé un écran connecté de profil public avec adresse. Aucun menu précis n'est donc inventé. Si l'utilisateur dispose d'un compte, l'action minimale est : ouvrir son propre profil et le flux de dépôt suivant les guides officiels, vérifier si l'interface affiche **sur une preuve datée** le même identifiant de profil et l'adresse publique Solana ; si ce sont deux écrans distincts, joindre un lien de transaction ou export autorisé qui les lie explicitement. Ne transmettre que l'identifiant/URL du profil, l'adresse **publique**, le type/référence de preuve et la date UTC. **Aucune clé privée, seed phrase ou copie de cookie.**

## Import local et revue

Le [modèle JSON](../config/r2-fomo-proof.example.json) et l'onglet **R2 réel** du tableau de bord demandent : profil, réseau, adresse publique, type et référence de preuve, date UTC, auteur, statut proposé et commentaire. Le validateur exige une vraie clé publique Solana de 32 octets décodés, refuse les URLs `/r/`, les dates futures et les références locales traversant les dossiers. L'import sauvegarde **toujours** `pending_review` et `onchain_unattributed`, même si le fichier prétend `verified`. Une revue distincte par une personne, avec motif, peut ensuite établir `fomo_verified` si l'artefact montre explicitement la liaison. Le type `other` ne peut pas être promu.

```bash
uv run rotation r2-fomo-import --root data/r2-20260926 --file config/ma-preuve-fomo.json
uv run rotation r2-fomo-review --root data/r2-20260926 --id ID_RETOURNE --reviewer VOTRE_NOM --decision verified --comment "Profil et adresse visibles ensemble dans la preuve datée"
```

Le premier appel local est réversible par la revue `rejected` ; la preuve n'est ni envoyée à Fomo ni traitée comme instruction financière. Le tableau de bord peut importer et exporter les fiches ; il n'a pas de bouton d'approbation automatique. Les preuves restent sur le disque local dans `data/r2-20260926/fomo-proofs.sqlite`. Une URL de preuve est une **référence**, jamais une invitation du moteur à exécuter son contenu.
