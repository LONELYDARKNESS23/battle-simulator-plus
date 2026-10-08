// Raster materials are loaded once; the tactical overlays remain crisp at any scale.
export const ground = new Image();
export const soldier = new Image();
export function loadArt(onLoad) {
  for (const [image, url] of [[ground, '/assets/ground.png'], [soldier, '/assets/soldier.png']]) {
    image.onload = onLoad;
    image.src = url;
  }
}

export function drawFigure(ctx, u, x, y, s, selected, directions) {
  const angle = (u.facing ?? (u.team === 'blue' ? 0 : 180)) * Math.PI / 180;
  const color = u.team === 'blue' ? '#b2ffdb' : '#ffae8e';
  ctx.save();
  ctx.translate(x, y);
  // A soft contact shadow separates the miniature from the textured floor.
  const shadow = ctx.createRadialGradient(2, 4, 1, 2, 4, s * .39);
  shadow.addColorStop(0, '#000000c0');
  shadow.addColorStop(1, '#00000000');
  ctx.fillStyle = shadow;
  ctx.fillRect(-s * .45, -s * .4, s * .9, s * .9);
  ctx.rotate(angle);
  if (directions) {
    if (selected) {
      const cone = ctx.createRadialGradient(0, 0, s * .25, 0, 0, s * 1.15);
      cone.addColorStop(0, color + '30');
      cone.addColorStop(1, color + '00');
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, s * 1.15, -.40, .40);
      ctx.closePath();
      ctx.fillStyle = cone;
      ctx.fill();
    }
    ctx.beginPath();
    ctx.moveTo(s * .55, 0);
    ctx.lineTo(s * .39, -s * .105);
    ctx.lineTo(s * .43, 0);
    ctx.lineTo(s * .39, s * .105);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.strokeStyle = '#071310';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fill();
  }
  if (soldier.complete && soldier.naturalWidth) {
    const size = s * (u.role === 'heavy' ? 1.02 : .90);
    ctx.filter = u.team === 'red' ? 'sepia(.55) saturate(1.25)' : 'none';
    ctx.drawImage(soldier, -size / 2, -size / 2, size, size);
    ctx.filter = 'none';
  } else {
    const metal = ctx.createLinearGradient(-s * .2, -s * .2, s * .2, s * .2);
    metal.addColorStop(0, '#c2c9a8');
    metal.addColorStop(.45, '#637761');
    metal.addColorStop(1, '#26382f');
    ctx.fillStyle = metal;
    ctx.beginPath();
    ctx.ellipse(-s * .04, 0, s * .22, s * .27, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#171e21';
    ctx.fillRect(s * .08, s * .08, s * .35, s * .08);
    ctx.beginPath();
    ctx.arc(s * .06, -s * .02, s * .13, 0, Math.PI * 2);
    ctx.fillStyle = metal;
    ctx.fill();
  }
  // Class equipment and team markers supplement the shared infantry silhouette.
  ctx.fillStyle = color;
  ctx.fillRect(-s * .05, -s * .22, s * .14, s * .04);
  if (u.role === 'ranger') {
    ctx.fillStyle = '#161e20';
    ctx.fillRect(s * .20, s * .09, s * .25, s * .045);
    ctx.fillStyle = '#aac8c4';
    ctx.fillRect(s * .40, s * .09, s * .06, s * .025);
  } else if (u.role === 'medic') {
    ctx.fillStyle = '#e9eee1';
    ctx.fillRect(-s * .22, -s * .085, s * .12, s * .17);
    ctx.fillStyle = '#347760';
    ctx.fillRect(-s * .18, -s * .055, s * .035, s * .11);
    ctx.fillRect(-s * .21, -s * .018, s * .095, s * .035);
  } else if (u.role === 'heavy') {
    ctx.fillStyle = '#9d9a7c';
    for (let i = 0; i < 4; i++) ctx.fillRect(-s * .18 + i * s * .055, s * .19, s * .035, s * .07);
  }
  ctx.restore();
}
