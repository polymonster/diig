// Discogs genre + style taxonomy for filter typeaheads.
// Discogs has no "list all styles" endpoint, so this is a curated list — the
// 15 official genres plus a broad, electronic-weighted set of styles. Free-typed
// values are still allowed in the UI, so anything missing here can be entered by
// hand. Keep this consistent with the native app's list in app/code/main.cpp
// (k_discogs_genres / k_discogs_styles).

export const DISCOGS_GENRES: string[] = [
  'Blues',
  'Brass & Military',
  "Children's",
  'Classical',
  'Electronic',
  'Folk, World, & Country',
  'Funk / Soul',
  'Hip Hop',
  'Jazz',
  'Latin',
  'Non-Music',
  'Pop',
  'Reggae',
  'Rock',
  'Stage & Screen',
]

export const DISCOGS_STYLES: string[] = [
  // Electronic
  'Abstract', 'Acid', 'Acid House', 'Acid Jazz', 'Ambient', 'Bassline', 'Beatdown',
  'Berlin-School', 'Big Beat', 'Breakbeat', 'Breaks', 'Breakcore', 'Broken Beat',
  'Chiptune', 'Dance-pop', 'Dark Ambient', 'Darkwave', 'Deep House', 'Disco',
  'Disco Polo', 'Downtempo', 'Drone', 'Drum n Bass', 'Dub', 'Dub Techno', 'Dubstep',
  'EBM', 'Electro', 'Electroclash', 'Electronic', 'Euro House', 'Euro-Disco',
  'Eurodance', 'Experimental', 'Freestyle', 'Future Jazz', 'Gabber', 'Garage House',
  'Ghetto', 'Ghetto House', 'Glitch', 'Goa Trance', 'Grime', 'Hard House',
  'Hard Techno', 'Hard Trance', 'Hardcore', 'Hardstyle', 'Happy Hardcore', 'Hi NRG',
  'House', 'IDM', 'Illbient', 'Industrial', 'Italo-Disco', 'Italodance', 'Jungle',
  'Juke', 'Leftfield', 'Minimal', 'Minimal Techno', 'Modern Classical', 'Musique Concrète',
  'Neofolk', 'New Age', 'New Beat', 'Noise', 'Nu-Disco', 'Progressive House',
  'Progressive Trance', 'Psy-Trance', 'Rhythmic Noise', 'Schranz', 'Speed Garage',
  'Speedcore', 'Synth-pop', 'Synthwave', 'Tech House', 'Techno', 'Trance', 'Tribal',
  'Tribal House', 'Trip Hop', 'UK Garage', 'Vaporwave', 'Witch House',
  // Hip Hop
  'Boom Bap', 'Conscious', 'Cut-up/DJ', 'Gangsta', 'G-Funk', 'Instrumental',
  'Jazzy Hip-Hop', 'Trap', 'Turntablism',
  // Rock
  'Acoustic', 'Alternative Rock', 'Art Rock', 'Blues Rock', 'Classic Rock',
  'Death Metal', 'Doom Metal', 'Emo', 'Folk Rock', 'Garage Rock', 'Glam',
  'Goth Rock', 'Grunge', 'Hard Rock', 'Heavy Metal', 'Indie Rock', 'Krautrock',
  'Lo-Fi', 'Math Rock', 'New Wave', 'No Wave', 'Post-Punk', 'Post-Rock',
  'Prog Rock', 'Psychedelic Rock', 'Punk', 'Rock & Roll', 'Rockabilly',
  'Shoegaze', 'Ska', 'Space Rock', 'Stoner Rock', 'Surf', 'Thrash',
  // Funk / Soul
  'Afrobeat', 'Boogie', 'Contemporary R&B', 'Funk', 'Gospel', 'Neo Soul',
  'New Jack Swing', 'P.Funk', 'Rhythm & Blues', 'Soul', 'Swingbeat',
  // Jazz
  'Bebop', 'Big Band', 'Bossa Nova', 'Contemporary Jazz', 'Cool Jazz',
  'Free Jazz', 'Fusion', 'Hard Bop', 'Jazz-Funk', 'Latin Jazz', 'Modal',
  'Post Bop', 'Smooth Jazz', 'Soul-Jazz', 'Spiritual Jazz', 'Swing',
  // Reggae
  'Dancehall', 'Dub Poetry', 'Lovers Rock', 'Ragga', 'Reggae', 'Reggae-Pop',
  'Rocksteady', 'Roots Reggae', 'Ska', 'Steppers',
  // Funk World & Country / Latin / Folk
  'Afro-Cuban', 'Cajun', 'Celtic', 'Cumbia', 'Flamenco', 'Folk', 'Highlife',
  'Salsa', 'Samba', 'Soukous', 'Zouk',
  // Pop / other
  'Ballad', 'Bollywood', 'Chanson', 'City Pop', 'Europop', 'J-pop', 'K-pop',
  'Novelty', 'Schlager', 'Vocal',
]
