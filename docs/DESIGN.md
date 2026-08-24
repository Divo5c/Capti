Capti Design System

Brand:
- Name: Capti
- Style: Modern Creator / Video Studio
- Accent: Yellow

Themes:
- Dark
- Light
- Yellow

Typography:
- Display: Nevera (Titel / große Überschriften)
- Technical: Orbitron Medium (technische Elemente, Zeiten, Zahlen)
- Body: Prociono (normaler UI-Text)
- Signature: Electroharmonix ("Erstellt von Diraj Voruganti")

Fonts werden als private Prozess-Fonts aus assets/fonts/ geladen
(AddFontResourceEx + FR_PRIVATE) – keine dauerhafte Windows-Installation.
Zugriff ausschließlich über ui/fonts.py -> FontManager.get(role, size).

Theme-Tokens (ui/theme.py, für jedes Theme definiert):
- background          App-Hintergrund
- surface             Karten / Panels
- surface_secondary   Sekundäre Flächen / Hover-Zustände
- text                Primärer Text
- text_secondary      Sekundärer Text / Hinweise
- accent              Capti Yellow (#ffd60a)
- accent_hover        Akzent bei Hover
- border              Rahmenlinien
- success             Erfolgs-Feedback
- error               Fehler-Feedback

Typography-Hierarchie:
- Display XL:  display, 32+   (Screen-Titel)
- Heading:     display, 20    (Sektionen)
- Body:        body, 14–16    (Standardtext)
- Caption:     body, 12       (Hinweise, sekundär)
- Technical:   technical, 12–14 (Zeiten, Fortschritt, Zahlen)
- Signature:   signature, 16–18 (Footer)

Spacing & Radius:
- Spacing-Skala: 4 / 8 / 12 / 16 / 24 / 32 px
- Screen-Padding: 24 px, Card-Padding: 16–20 px
- Radius: Cards 12 px, Buttons 8 px, Inputs 6 px
- Mindestens 8 px Abstand zwischen interaktiven Elementen

Navigation:
- Home
- New Project
- Caption Style
- Processing
- Result
- Settings

Principles:
- Keine überfüllten Screens
- Ein Hauptzweck pro Seite
- Große visuelle Hierarchie
- Viel Whitespace
- Moderne Cards
- Klare Buttons
- Keine unnötigen Dialoge