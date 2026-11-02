(() => {
  const status=document.getElementById('travel-job');
  for(const form of document.querySelectorAll('[data-travel-run]')) form.addEventListener('submit',()=>{
    form.querySelector('button').disabled=true;
    status.textContent='Starting travel update…';
  });
  if(status?.dataset.state==='running') {
    let attempts=0;
    const poll=async()=>{
      try {
        const response=await fetch('/day-travel/status',{headers:{Accept:'application/json'},cache:'no-store'});
        if(!response.ok) throw Error('Unavailable');
        const job=await response.json();
        if(job.day!==status.dataset.day || !job.state) {status.textContent='Request no longer running. Reload to try again.';return;}
        status.textContent=job.message;
        if(job.state==='complete'||job.state==='failed') {location.reload();return;}
        if(++attempts<100) setTimeout(poll,2000);
        else status.textContent='This is taking longer than expected. Reload to check the last saved result.';
      }catch {status.textContent='Progress unavailable. Reload to check the last saved result.';}
    };
    setTimeout(poll,800);
  }
  const container=document.getElementById('travel-map'),data=document.getElementById('travel-map-data');
  if(!container||!data||!window.L)return;
  const plan=JSON.parse(data.textContent),map=L.map(container,{scrollWheelZoom:false});
  const bounds=[];
  plan.points.forEach((point,index)=>{
    if(!point.point)return;
    bounds.push(point.point);
    const label=document.createElement('span');label.textContent=`${index+1}. ${point.label}`;
    L.circleMarker(point.point,{radius:8,color:'#6f153b',fillOpacity:.9}).addTo(map).bindTooltip(label,{permanent:true,direction:'top'});
  });
  plan.legs.forEach(leg=>{
    const street=leg.geometry?.length>1;
    const coords=street?leg.geometry:[leg.origin.point,leg.destination.point].filter(Boolean);
    if(coords.length<2)return;
    L.polyline(coords,{color:leg.mode==='driving'?'#6f153b':leg.mode==='walking'?'#136252':'#31569a',weight:4,opacity:.8,dashArray:street?null:'5,8'}).addTo(map);
  });
  if(bounds.length)map.fitBounds(bounds,{padding:[35,45],maxZoom:15});else map.setView([52.48,-1.9],10);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
})();
