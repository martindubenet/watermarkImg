# Watermark batch — Quick Action Automator

Ajoute un watermark (SVG ou PNG24) en bas à gauche d'un lot d'images, directement depuis le Finder.

## 1. Installer les dépendances (une seule fois)

Ouvre ton logiciel Terminal et lance :

```bash
# Homebrew doit déjà être installé (sinon : https://brew.sh)
brew install librsvg          # fournit rsvg-convert, pour rasteriser le SVG

which python3                 # note le chemin retourné, ex: /opt/homebrew/bin/python3
pip3 install -U Pillow        # librairie de traitement d'image (version 11+ requise pour l'XMP des JPEG)
pip3 install pillow-heif      # support de lecture HEIC/HEIF/AVIF (photos iPhone)
```

`pillow-heif` embarque généralement sa propre copie de `libheif` dans le paquet Python — pas besoin d'installer quoi que ce soit via Homebrew pour ça. Si jamais `pip3 install pillow-heif` échoue en essayant de compiler depuis les sources, lance `brew install libheif` puis relance la commande pip.

Garde en note le chemin exact retourné par `which python3` — tu en auras besoin à l'étape 3.

> Tu as déjà un alias `cdscript` dans ton `.zshrc` qui pointe vers ce dossier (`/Volumes/usbgt7/aiScripts`) — utilise-le pour t'y déplacer en Terminal si tu veux lancer les commandes ci-dessus directement depuis ce dossier. Note que cet alias est propre à ton Terminal interactif : Automator ne le voit pas (voir étape 2 ci-dessous), il reste donc utile seulement pour ton usage manuel.

## 2. Créer un lien symbolique vers le script (déjà sur le disque externe)

Chez toi, le script vit en permanence sur le disque externe, dans `/Volumes/usbgT7/aiScripts/watermarkImg/` — inutile de le déplacer ou d'en faire une copie. Mais Automator référence le script par un chemin absolu sous `$HOME` (voir étape 3.6) et ne charge pas les alias de ton `.zshrc` (comme `cdscript`), donc il ne peut pas retrouver le disque externe tout seul.

La solution, à faire une seule fois dans ton logiciel Terminal :

```bash
ln -s /Volumes/usbgT7/aiScripts ~/aiScripts
chmod +x ~/aiScripts/watermarkImg/add_watermark.py
```

Ce lien fait pointer `~/aiScripts/watermarkImg/add_watermark.py` (le chemin utilisé par Automator à l'étape 3.6) directement vers le fichier réel sur `usbgT7` — une seule source de vérité, pas de copie à maintenir à jour. Si le disque `usbgT7` n'est pas branché, le lien restera en place mais cassé jusqu'à ce que tu le reconnectes.

## 3. Créer la Quick Action dans Automator

1. Ouvre **Automator** (Spotlight → « Automator »).
2. **Fichier > Nouveau**, choisis **Quick Action** (ou « Action rapide »).
3. En haut du document, règle :
   - **Workflow receives current** → **image files**
   - **in** → **Finder**
4. Dans la bibliothèque d'actions à gauche, cherche **Run Shell Script** (« Exécuter un script Shell ») et glisse-la dans la zone de droite.
5. Dans cette action, règle :
   - **Shell** → `/bin/zsh`
   - **Pass input** → **as arguments**
6. Toujours dans Automator, remplace le contenu de la boîte de script (de l'action **Run Shell Script**) par (en remplaçant le chemin de `python3` par celui noté à l'étape 1) :

   ```bash
   /opt/homebrew/bin/python3 "$HOME/aiScripts/watermarkImg/add_watermark.py" "$@"
   ```

   (Ce chemin fonctionne grâce au lien symbolique créé à l'étape 2 — il pointe vers le fichier réel sur `usbgT7`.)

7. **Fichier > Enregistrer**, donne-lui un nom clair, ex. **Ajouter watermark**.

C'est tout — pas d'icône à dessiner, pas de bundle à signer, Automator s'occupe de tout créer proprement dans `~/Library/Services/`.

## 4. Utilisation

1. Dans le Finder, sélectionne une ou plusieurs images (jpg, jpeg, png, webp, heic, heif, avif, tif, tiff, bmp).
2. Clic droit → **Services** (ou directement dans le menu contextuel selon la version de macOS) → **Ajouter watermark**.
3. La fenêtre **Add Watermark** te demande de choisir le fichier SVG (ou PNG24) du watermark. Au bas de cette même fenêtre, des options permettent de régler le nom des fichiers générés (voir ci-dessous).
   - Clique **Cancel** pour tout annuler : le script s'arrête sans aucun message.
4. Le script traite toutes les images sélectionnées et affiche un résumé à la fin.

Chaque image d'origine reste intacte ; une copie watermarquée est créée à côté, par ex. `photo.jpg` → `photo___photo-MartinDube.jpg`.

### Options (zone de gauche) : ajouter la date de prise de vue

| Option | Par défaut | Effet |
| --- | --- | --- |
| **Add date created** (switch) | ON | Ajoute la date de prise de vue au nom du fichier, séparée par une espace. À OFF, les deux sous-options sont masquées et la boîte se réduit à cette seule ligne. |
| 1. **Position relative to file name** : Before / After | Before | Place la date au début du nom (Before) ou après le suffixe (After). |
| 2. **Include hours and minutes** | coché | Format `YYMMDD-HHhMM` (le « h » minuscule sépare l'heure des minutes). Décoché : `YYMMDD` seulement. |

Exemples pour `photo.jpg` prise le 25 septembre 2026 à 14 h 32 :

- Before (par défaut) : `260925-14h32 photo___photo-MartinDube.jpg`
- After : `photo___photo-MartinDube 260925-14h32.jpg`
- Sans heures et minutes : `260925 photo___photo-MartinDube.jpg`
- Add date created à OFF : `photo___photo-MartinDube.jpg`

La date est lue dans les métadonnées EXIF de la photo (`DateTimeOriginal`, le moment de la prise). Si l'image n'a pas d'EXIF (capture d'écran, export web…), c'est la date de création du fichier qui est utilisée.

Le suffixe et les formats de date se modifient en haut du script : `WATERMARK_SUFFIX`, `DATE_FORMAT_FULL`, `DATE_FORMAT_DAY`, `DATE_SEPARATOR`.

### Option (zone de droite) : Resize for sharing

Case **Resize for sharing**, cochée par défaut. Elle réduit l'image pour que son plus grand côté fasse au maximum **1350 px** : la hauteur pour une photo en portrait, la largeur pour une photo en paysage. Les proportions sont conservées, et une image déjà plus petite n'est jamais agrandie.

- Quand la switch **Add date created** est à OFF, la phrase explicative est masquée aussi : les deux zones ne montrent plus que leur première ligne. La case reste cliquable.
- La réduction se fait avant l'ajout du watermark, qui est donc dimensionné sur l'image finale (15 % de sa largeur).
- Les dimensions enregistrées dans l'EXIF (`PixelXDimension` / `PixelYDimension`) sont mises à jour.
- La limite se modifie en haut du script avec `RESIZE_MAX_LONG_SIDE`. Le texte de la fenêtre se met à jour tout seul.

**Cas particulier HEIC / HEIF / AVIF :** ces formats sont lus sans problème, mais la copie watermarquée est toujours enregistrée en `.png` (PNG24, sans perte) plutôt que dans le format d'origine (ex. `IMG_1234.heic` → `260925-14h32 IMG_1234___photo-MartinDube.png`). Ré-encoder proprement en HEIC/AVIF demande des encodeurs supplémentaires peu fiables à installer, alors que PNG évite toute compression avec perte. Si tu veux ensuite convertir ces PNG en AVIF, XnConvert.app en lot fait très bien le travail.

## Rappel des règles appliquées par le script

- Position : bas-gauche, avec une marge de 20 px (ajustable via `MARGIN_PX` en haut du script).
- Largeur du watermark : toujours 15 % de la largeur de l'image (`WM_WIDTH_RATIO`), avec un minimum de 50 px pour les très petites images (`MIN_WM_WIDTH`).
- Le résultat est aplati (flatten) sur un fond blanc opaque avant l'enregistrement.
- Un SVG sans attribut `viewBox` (ou `viewbox`) est refusé.
- Une photo prise en mode portrait (orientation EXIF) est d'abord remise à l'endroit, pour que le watermark tombe toujours dans le coin bas-gauche visible.

## Qualité et métadonnées conservées

- **JPEG :** qualité 95 % (`JPEG_QUALITY`) avec couleurs en pleine résolution 4:4:4 (`JPEG_SUBSAMPLING = 0`). Au-delà de 95 %, le fichier grossit beaucoup sans gain visible.
- **WebP :** enregistré sans perte (lossless).
- **Profil de couleur ICC** conservé (ex. Display P3 des iPhone), pour que les couleurs ne changent pas.
- **EXIF conservé au complet :** appareil, objectif, réglages, dates et géolocalisation (GPS).
- **Auteur ajouté** dans chaque copie (constantes `AUTHOR_NAME` et `AUTHOR_URL` en haut du script) :
  - EXIF `Artist` : Martin Dubé
  - XMP `dc:creator` : Martin Dubé (le champ « Créateur » dans Lightroom, Photoshop, Bridge)
  - XMP IPTC `CreatorContactInfo › CiUrlWork` : https://photo.martindube.net (le champ « Site web » du créateur)
- Si l'image d'origine contient déjà de l'XMP (ex. Lightroom), il est conservé et ces champs y sont ajoutés, sans écraser un créateur ou un site web déjà présent.
- **Limites :** le BMP ne peut contenir aucune métadonnée. En TIFF, le champ EXIF `Artist` s'écrit sans accent (« Martin Dube ») ; l'XMP garde « Martin Dubé ».

Pour vérifier les métadonnées d'une copie, dans ton logiciel Terminal (après `brew install exiftool`) : `exiftool -a -G1 "nom-du-fichier.jpg"`.

## Dépannage

- **« rsvg-convert not found »** → l'install Homebrew n'est pas allée au bout, ou le chemin dans le script Automator ne pointe pas vers le bon `python3`/`rsvg-convert` (Apple Silicon : `/opt/homebrew/bin/`, Intel : `/usr/local/bin/`).
- **Aucune boîte de dialogue n'apparaît** → vérifie que **Pass input** est bien réglé sur **as arguments**, pas « to stdin ».
- **Les options n'apparaissent pas (ancienne fenêtre sans options)** → la fenêtre avec options n'a pas pu s'ouvrir et le script est revenu à l'ancien sélecteur, avec les options par défaut. Pour voir la raison, lance le script depuis ton logiciel Terminal : `/opt/homebrew/bin/python3 ~/aiScripts/watermarkImg/add_watermark.py ~/Desktop/une-photo.jpg` — le message commençant par `JXA open panel failed:` s'affiche dans le Terminal.
- **Mode diagnostic (`WM_DEBUG=1`)** → si la fenêtre ou les options se comportent bizarrement (par ex. après une mise à jour de macOS : options absentes, animation de la switch qui saute), lance le script avec ce préfixe dans ton logiciel Terminal (glisse une vraie photo depuis le Finder à la place du chemin d'exemple) :

  ```bash
  WM_DEBUG=1 /opt/homebrew/bin/python3 ~/aiScripts/watermarkImg/add_watermark.py ~/Desktop/une-photo.jpg
  ```

  Dans la fenêtre, bascule la switch OFF puis ON, puis clique **Cancel**. Des lignes `[wm-debug]` s'affichent alors dans le Terminal :
  - `timer tick OK` / `timers worked: true` → les minuteries fonctionnent, donc l'animation de la switch aussi. Si c'est `false`, la switch change d'état sans animation.
  - `view count` et `classes` → la structure interne de la fenêtre système, utile pour comprendre ce qui a changé côté macOS.
  - `JXA open panel failed: …` → la fenêtre avec options n'a pas pu s'ouvrir ; le message qui suit donne la cause.

  Ce mode ne change pas le comportement du script (si tu cliques **Submit**, les images sont traitées normalement) : il ajoute seulement ces informations dans le Terminal.
- **Alerte Finder « The action "Run Shell Script" encountered an error »** → le script ne devrait plus la provoquer (Cancel et erreurs connues se terminent proprement). Si elle réapparaît, c'est une erreur inattendue : lance le script depuis le Terminal (commande ci-dessus) pour voir le détail.
- **La Quick Action n'apparaît pas dans le menu Services** → dans **Réglages Système > Clavier > Raccourcis clavier > Services**, vérifie qu'elle est cochée/activée.