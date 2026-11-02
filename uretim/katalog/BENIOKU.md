# Türkiye'nin hayvanları kataloğu (uygulamadaki "Türkiye'nin hayvanları")

1. `turler.json`: GBIF'te Türkiye kaydı olan hayvan türleri (sınıflandırma ve grup).
2. `zenginlestir.py` (GitHub Actions, `katalog.yml`): Vikiveri'den Türkçe/İngilizce adlar, IUCN durumu, Vikipedi özetleri ve Wikimedia Commons fotoğrafları; çıktı "katalog" sürümündeki `katalog_wiki.zip`.
3. `media2.py`: Commons'ta fotoğrafı olmayan türler için iNaturalist'teki CC0 / CC BY / CC BY-SA fotoğraflar (ticari kullanıma uygun lisanslar).
4. `build_katalog.py`: hepsini birleştirip uygulamanın `assets/fauna/` klasörünü üretir (katalog.json.gz, aciklama.json.gz, img/*.webp).

`endemik_vikipedi.json`: Vikipedi metninde açıkça "Türkiye'ye endemik / endemic to Turkey" yazan türlerin GBIF anahtarları (Vikiveri'de yalnızca birkaç tür işaretli).
