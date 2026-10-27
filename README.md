# CTI Radar

CTI firmalarının bloglarını ve güvenlik haber sitelerinin RSS/Atom akışlarını tek bir panoda toplar.
Sunucu akışları belirli aralıklarla kendisi çeker; sayfa açıkken her dakika yeni kayıtları gösterir.

## Çalıştırma

Yalnızca Python 3.9+ gerekir, ek paket yok.

```bash
python3 server.py              # http://localhost:8080
python3 server.py --port 9000  # farklı port
```

Docker ile:

```bash
docker build -t cti-radar .
docker run -d -p 8080:8080 --name cti-radar cti-radar
```

## Özellikler

- **Akış** görünümü: tüm kaynaklar güne göre gruplanmış tek zaman çizelgesi.
- **Pano** görünümü: her kaynak için son 7 yazıyı gösteren kartlar; erişilemeyen kaynak hata nedeniyle görünür.
- Başlığa tıklamak yazıyı yeni sekmede açar ve okundu olarak işaretler.
- Son ziyaretten sonra gelen kayıtlar **YENİ** etiketi alır.
- Tür (Haber / CTI blog / Bildiri), zaman aralığı ve kaynak filtresi; başlık ve özette arama.
- **Şimdi yenile** düğmesi beklemeden tüm kaynakları yeniden tarar.
- Filtreler, okundu bilgisi ve görünüm tarayıcıda saklanır.
- Kayıtlar `cache.json` dosyasına yazılır; sunucu yeniden başlayınca eski veriyle açılır.

## Kaynak ekleme / çıkarma

`feeds.json` dosyasını düzenleyin. Değişiklik bir sonraki taramada (veya **Şimdi yenile** ile) uygulanır, yeniden başlatma gerekmez.

```json
{ "name": "Kaynak adı", "url": "https://ornek.com/feed/", "category": "cti" }
```

`category` değeri `news`, `cti` veya `advisory` olabilir.
`refresh_minutes` tarama aralığını (varsayılan 15 dk), `max_items_per_feed` kaynak başına alınacak kayıt sayısını belirler.

Kenar çubuğunda kırmızı noktalı bir kaynak erişilemiyor demektir; fareyle üzerine gelince hata nedeni görünür.
Akış adresi değişmiş olabilir: sitenin RSS bağlantısını bulup `feeds.json` içinde güncelleyin.
