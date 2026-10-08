# Растровые ресурсы RIFT 1.1

Созданы 8 октября 2026 встроенным инструментом `image_gen` для этой игры. Интернет при запуске не используется. Исходные PNG сохранены в `web/assets/`; код накладывает тени, маркеры команд и оборудование классов. Один общий спрайт пехотинца используется как основа четырёх классов. Это 2D-спрайты с объёмным изображением, не 3D-движок.

## Ground — `web/assets/ground.png`

Final prompt:

> Use case: stylized-concept. Asset type: raster ground texture for a top-down tactical game. Create a square seamless-looking orthographic overhead texture of a worn industrial concrete courtyard, finely mottled charcoal gray concrete with warm gray aggregate, fine cracks, faded subtle maintenance paint fragments, small oil stains and traces of dry moss. Photorealistic material detail, game-ready albedo-style diffuse lighting, restrained contrast, overall medium dark value. Entire frame is flat walkable ground. No walls, no objects, no people, no text, no symbols, no grid, no strong perspective, no vignette. This will sit beneath tactical grid and characters, so subtle background detail is essential.

## Soldier — `web/assets/soldier.png`

Generated with a transparent background. Final prompt:

> Use case: stylized-concept. Asset type: game sprite on transparent background. One single futuristic tactical infantry soldier seen STRICTLY FROM DIRECTLY ABOVE, orthographic bird's eye top-down camera looking vertically down at crown of helmet, shoulders and boots. Soldier faces RIGHT (east) and holds a long assault rifle clearly aimed horizontally toward the RIGHT edge. Head and rifle pointing right, backpack on left. Full figure centered, occupies 80 percent of canvas with generous transparent margin, no cropping. Olive gray segmented armored suit, small pale mint identification strips on both shoulder pads, worn steel weapon, sculpted realistic material texture and subtle highlights. Pre-rendered 3D tactical miniature quality, clean silhouette legible when reduced to 64px. Character only, absolutely no ground, no lettering, no UI, no circle, no frame, no cast shadow outside figure. Weapon and posture make facing direction unmistakable. Square canvas. True transparent background.

Направление отсчитывается по часовой стрелке: 0° вправо, 90° вниз, 180° влево, 270° вверх. При перемещении используется последний фактический шаг пути; при ответном огне стрелок поворачивается к цели. Граната ориентирует бойца на точку броска. Маркер направления не является сектором видимости или ограничением огня.
