# Watermark batch —  macOS Quick Action Automator <img width="48px" src="https://static.wikia.nocookie.net/ipod/images/a/ab/Automator.png/revision/latest?cb=20160908152407" alt="Otto l’Automator" />

[English](README.md) · **Français**

Ajoute un watermark (SVG ou PNG24) en bas à gauche d'un lot d'images, directement depuis le Finder.

<img width="60%" src="img_watermarkImg.avif" alt="Screenshot">

> Scripts apparentés dans `aiScripts/` : pour ajouter la date de prise de vue au nom des fichiers, utilise [`addDateImg`](../addDateImg/README.md) ; pour rendre les noms de fichiers compatibles avec un serveur (et créer des copies AVIF), utilise [`renameForServer`](../renameForServer/README.md).

## Fonctionnement

- `add_watermark.py` — le script Python appelé par la Quick Action. Il fait tout le traitement d'image.
- `AddWatermark.app` — une petite app macOS native (source dans `AddWatermarkApp/`, compilée sur ton Mac avec `build_app.sh`) qui ne sert qu'à afficher la fenêtre **Add Copyrights Watermark to Image** et à envoyer la notification de fin.
- `watermarks/` — le dossier où se trouvent tes fichiers watermark (SVG/PNG).

Si `AddWatermark.app` est absente ou échoue, le script revient automatiquement à une simple liste native (voir [Solution de repli et retour en arrière](#solution-de-repli-et-retour-en-arrière)).

## 1. Installer les dépendances (une seule fois)

Ouvre ton app Terminal et lance :

```bash
# Homebrew doit déjà être installé (sinon : https://brew.sh)
brew install librsvg          # fournit rsvg-convert, pour convertir le SVG en image

# Installer les bibliothèques Python pour le MÊME python3 que celui d'Automator (étape 4.6)
/opt/homebrew/bin/python3 -m pip install -U Pillow pillow-heif
```

- **Pillow** (11+) est la bibliothèque de traitement d'image ; **pillow-heif** lit les HEIC/HEIF/AVIF (photos d'iPhone).
- ⚠ Un simple `pip3` peut installer dans un autre Python que `/opt/homebrew/bin/python3`. Vérifie que le bon a tout ce qu'il faut :

  ```bash
  /opt/homebrew/bin/python3 -c "import sys, PIL; print(sys.version.split()[0], PIL.__version__)"
  ```

- `pillow-heif` inclut généralement sa propre copie de `libheif`. Si l'installation échoue en essayant de compiler depuis les sources, lance `brew install libheif`, puis relance la commande pip.
- Les **Xcode Command Line Tools** sont nécessaires pour compiler l'app (étape 3). Vérifie avec `xcode-select -p` ; si une erreur s'affiche, lance `xcode-select --install`.

> Tu as déjà un alias `cdscript` dans ton `.zshrc` qui pointe vers ce dossier (`/Volumes/usbgt7/aiScripts`). Utilise-le pour t'y déplacer dans le Terminal si tu veux lancer des commandes depuis ce dossier. Cet alias n'existe que dans ton Terminal interactif : Automator ne le voit pas (voir l'étape 2), il ne sert donc qu'en usage manuel.

## 2. Créer un lien symbolique vers le dossier des scripts (déjà sur le disque externe)

> <mark>⚠</mark> NOTE IMPORTANTE : dans les instructions suivantes, le terme « <mark>usbgT7</mark> » désigne mon disque dur USB externe personnel. Si ton script est sur le disque principal de ton Mac, ignore cette étape (#2).

Les scripts restent en permanence sur le disque externe, dans `/Volumes/usbgT7/aiScripts/` : inutile de les déplacer ou de les copier. Mais Automator désigne le script par un chemin absolu sous `$HOME` (voir l'étape 4.6) et ne charge pas les alias de ton `.zshrc` (comme `cdscript`) : il ne peut donc pas trouver le disque externe tout seul.

La solution, à faire une seule fois dans ton app Terminal :

```bash
ln -s /Volumes/usbgT7/aiScripts ~/aiScripts
```

Ce seul lien couvre tous les dossiers de scripts de `aiScripts/` (celui-ci, `addDateImg/`, `renameForServer/`). Si le disque `usbgT7` n'est pas branché, le lien reste en place mais ne mène nulle part jusqu'à ce que tu rebranches le disque.

## 3. Compiler l'app (une fois, puis après chaque modification de `AddWatermarkApp/`)

Dans ton app Terminal :

```bash
~/aiScripts/watermarkImg/build_app.sh
```

La commande se termine par `Built: …/AddWatermark.app`. L'app est compilée et signée localement (signature ad hoc), donc macOS ne la bloque pas. Elle est ignorée par git : chaque Mac compile la sienne.

## 4. Créer la Quick Action dans Automator

1. Ouvre **Automator** (Spotlight → « Automator »).
2. **File > New**, choisis `Quick Action`.
3. En haut du document, règle :
   - **Workflow receives current** → `image files`
   - **in** → `Finder`
   - **Image** (*facultatif, choisis dans la liste une icône à associer à ce script*) → `Tag`
4. Dans la bibliothèque d'actions à gauche, cherche **Run Shell Script** et glisse-la dans la zone de droite.
5. Dans cette action, règle :
   - **Shell** → `/bin/zsh`
   - **Pass input** → `as arguments`
6. Toujours dans Automator, remplace le contenu de la boîte de script (dans l'action **Run Shell Script**) par :

   ```bash
   /opt/homebrew/bin/python3 "$HOME/aiScripts/watermarkImg/add_watermark.py" "$@"
   ```

   (Ce chemin fonctionne grâce au lien symbolique créé à l'étape 2 : il pointe vers le vrai fichier sur `usbgT7`.)

7. **File > Save**, et donne-lui un nom clair, par exemple **Add watermark to image file**.

Automator l'enregistre dans `~/Library/Services/`. Pour la modifier plus tard : dans Automator, **Open an Existing Document…**, appuie sur **Cmd+Shift+G**, tape `~/Library/Services` et choisis le fichier `.workflow`.

## 5. Ajouter tes fichiers watermark

Copie tes fichiers watermark (SVG de préférence, PNG24 accepté) dans `watermarks/`. Un SVG doit avoir un attribut `viewBox` (ou `viewbox`).

## 6. Utilisation

1. Dans le Finder, sélectionne une ou plusieurs images (jpg, jpeg, png, webp, heic, heif, avif, tif, tiff, bmp).
2. Clic droit → **Quick Actions** (ou **Services**, selon ta version de macOS) → **Add watermark to image file**.
3. La fenêtre **Add Copyrights Watermark to Image** s'ouvre avec le dernier watermark utilisé (ou le premier fichier de `watermarks/`) :

   | Élément | Effet |
   | --- | --- |
   | Aperçu (128 × 128) et **File** | Le watermark sélectionné. Le carré pointillé en bas à gauche de l'aperçu indique où le watermark sera placé. |
   | **Apply this watermark to** | Nombre d'images sélectionnées. |
   | **Resize for Sharing** (switch) | Réduit les copies (voir plus bas). Son dernier état est mémorisé. |
   | **Change Watermark…** | Ouvre un sélecteur de fichier (dans `watermarks/`) pour choisir un autre SVG/PNG. Le choix est mémorisé. |
   | **Cancel** (ou **Esc**) | Arrête tout, sans aucun message. |
   | **Submit** (ou **Return**) | Traite les images. |

   Le bouton rouge ferme la fenêtre comme **Cancel** ; le jaune la réduit dans le Dock. Avec la navigation au clavier activée, **Tab** suit l'ordre Submit → Resize for Sharing → Change Watermark… → Cancel.
4. Quand tout est terminé, une **notification** le confirme (par exemple « 12 image(s) processed successfully. »). Si des images ont échoué, un dialogue liste les erreurs à la place.

Chaque image originale reste intacte ; une copie avec le watermark est créée à côté. Par exemple, avec le watermark `ma signature photo.svg` : `photo.jpg` → `photo__ma-signature-photo_s.jpg`.

### Suffixe : le nom du fichier watermark

Le suffixe ajouté au nom de la copie est le nom du fichier watermark choisi (sans son extension), précédé de deux underscores (`__`). Ce nom est d'abord nettoyé pour être compatible avec le système de fichiers de macOS :

1. Tout caractère qui n'est ni une lettre ni un chiffre (espace, ponctuation, symbole, caractère refusé par macOS comme `:` ou `/`) devient un trait d'union `-`.
2. Les traits d'union consécutifs (issus d'un double espace ou de `--`, par exemple) sont réduits à un seul `-`.
3. Les traits d'union en début et en fin sont retirés. Les lettres accentuées sont conservées.
4. Un numéro en tête, utilisé pour ordonner les fichiers de `watermarks/` (par exemple `1 `, `02-`, `3_`), est retiré.

| Fichier watermark | Suffixe obtenu |
| --- | --- |
| `ma signature photo.svg` | `__ma-signature-photo` |
| `logo  (v2)--final.png` | `__logo-v2-final` |
| `Signé Martin_Dubé!!.svg` | `__Signé-Martin-Dubé` |
| `2 logo.png` | `__logo` |

Exemple : `fileName.jpg` + `ma signature photo.svg` → `fileName__ma-signature-photo.jpg`, ou `fileName__ma-signature-photo_s.jpg` avec **Resize for Sharing** activé.

Si le nom nettoyé est vide (par exemple un fichier nommé `...svg`), le suffixe `watermark` est utilisé à la place. Le séparateur se modifie en haut du script avec `WATERMARK_SUFFIX_PREFIX`.

### Resize for Sharing

Réduit l'image pour que son plus grand côté fasse au maximum **1350 px** : la hauteur pour une photo en portrait, la largeur pour une photo en paysage. Les proportions sont conservées, et une image déjà plus petite n'est jamais agrandie.

- Quand l'option est activée, `_s` est ajouté au suffixe : `photo__ma-signature-photo_s.jpg` (désactivée : `photo__ma-signature-photo.jpg`).
- La réduction se fait avant l'ajout du watermark, qui est donc dimensionné sur l'image finale (15 % de sa largeur).
- Les dimensions enregistrées dans l'EXIF (`PixelXDimension` / `PixelYDimension`) sont mises à jour.
- La limite se modifie en haut du script avec `RESIZE_MAX_LONG_SIDE` (la fenêtre affiche la valeur qu'elle reçoit).

**Cas particulier HEIC / HEIF / AVIF :** ces formats sont lus sans problème, mais la copie avec le watermark est toujours enregistrée en `.jpg` de haute qualité (95 %, couleurs 4:4:4) plutôt que dans le format d'origine (par exemple `IMG_1234.heic` → `IMG_1234__ma-signature-photo_s.jpg`) : réencoder en HEIC/AVIF demande des encodeurs supplémentaires peu fiables à installer. Pour obtenir ensuite des fichiers AVIF, utilise [`renameForServer`](../renameForServer/README.md) avec son option AVIF.

## Règles appliquées par le script

- Position : en bas à gauche, avec une marge de 20 px (réglable avec `MARGIN_PX` en haut du script).
- Largeur du watermark : toujours 15 % de la largeur de l'image (`WM_WIDTH_RATIO`), avec un minimum de 50 px pour les très petites images (`MIN_WM_WIDTH`).
- Le résultat est aplati sur un fond blanc opaque avant l'enregistrement.
- Un SVG sans attribut `viewBox` (ou `viewbox`) est refusé.
- Une photo prise en mode portrait (orientation EXIF) est d'abord remise à l'endroit, pour que le watermark tombe toujours dans le coin inférieur gauche visible.

## Qualité et métadonnées conservées

- **JPEG :** qualité 95 % (`JPEG_QUALITY`) avec couleurs 4:4:4 en pleine résolution (`JPEG_SUBSAMPLING = 0`). Au-delà de 95 %, le fichier grossit beaucoup sans gain visible.
- **WebP :** enregistré sans perte.
- **Profil de couleur ICC** conservé (par exemple le Display P3 de l'iPhone), pour que les couleurs ne changent pas.
- **EXIF complet conservé :** appareil, objectif, réglages, dates et géolocalisation (GPS).
- **Auteur ajouté** à chaque copie (constantes `AUTHOR_NAME` et `AUTHOR_URL` en haut du script) :
  - EXIF `Artist` : Martin Dubé
  - XMP `dc:creator` : Martin Dubé (le champ « Creator » dans Lightroom, Photoshop, Bridge)
  - XMP IPTC `CreatorContactInfo › CiUrlWork` : https://photo.martindube.net (le champ « Website » du créateur)
- Si l'image d'origine contient déjà du XMP (par exemple venant de Lightroom), il est conservé et ces champs y sont ajoutés, sans écraser un créateur ou un site web déjà présent.
- **Limites :** le BMP ne peut contenir aucune métadonnée. En TIFF, le champ EXIF `Artist` est écrit sans accent (« Martin Dube ») ; le XMP garde « Martin Dubé ».

Pour vérifier les métadonnées d'une copie, dans ton app Terminal (après `brew install exiftool`) : `exiftool -a -G1 "nom-du-fichier.jpg"`.

## Solution de repli et retour en arrière

La fenêtre native a été ajoutée parce que, depuis macOS 27.2, le sélecteur de fichier ouvert par un script lancé depuis le Finder perdait la plupart des clics. Si l'app devient un jour instable :

- **Repli immédiat, sans toucher au code :** dans le Finder, supprime ou renomme `AddWatermark.app`. Le script affiche alors une liste native : chaque fichier de `watermarks/` deux fois (`— resize for sharing` / `— full size`), plus `Other file…`, avec le dernier choix présélectionné.
- **Forcer la liste pour un test**, dans ton app Terminal : `WM_FORCE_LIST=1 /opt/homebrew/bin/python3 ~/aiScripts/watermarkImg/add_watermark.py ~/Desktop/une-photo.jpg`
- **Revenir au code avec la liste seulement :** le tag git `list-version` contient la version d'avant l'app (`git checkout list-version -- add_watermark.py`).

## Dépannage

- **« rsvg-convert not found »** → l'installation Homebrew n'est pas allée au bout (Apple Silicon : `/opt/homebrew/bin/`, Intel : `/usr/local/bin/`).
- **La liste s'affiche au lieu de la fenêtre** → `AddWatermark.app` est absente ou a échoué : recompile-la (étape 3). Pour savoir pourquoi, lance le script depuis ton app Terminal (commande ci-dessus, sans `WM_FORCE_LIST=1`) : le message qui commence par `AddWatermark.app gave no answer` s'y affiche.
- **Alerte d'autorisation « … wants access to control Finder »** → clique **Allow** : la liste et certains messages sont affichés par le Finder pour qu'ils reçoivent le focus. Tu peux revoir ce réglage dans **System Settings › Privacy & Security › Automation**.
- **Pas de notification à la fin** → la première fois, macOS demande si **Add Watermark** peut envoyer des notifications : clique **Allow**. Vérifie **System Settings › Notifications › Add Watermark** (style d'alerte **Temporary**) et qu'aucun mode Focus n'est actif : un Focus masque les bannières. Si macOS refuse les notifications de l'app, un petit dialogue qui se ferme tout seul après 3 secondes s'affiche à la place.
- **Aucun dialogue n'apparaît** → vérifie que **Pass input** est réglé sur `as arguments`, et non « to stdin ».
- **Alerte du Finder « The action "Run Shell Script" encountered an error »** → erreur inattendue : lance le script depuis le Terminal (commande ci-dessus) pour voir le détail.
- **La Quick Action n'apparaît pas dans le menu** → dans **System Settings › Keyboard › Keyboard Shortcuts › Services**, vérifie qu'elle est activée. Relancer le Finder (**Option**+clic droit sur son icône dans le Dock → **Relaunch**) peut aider.
