
const deep=[...document.querySelectorAll('details.deep')],modeButtons=[...document.querySelectorAll('.mode-bar button')];
function setMode(mode){deep.forEach(d=>d.open=mode==='full');modeButtons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));try{localStorage.setItem('notes-mode',mode)}catch(e){}}
modeButtons.forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
try{if(localStorage.getItem('notes-mode')==='full')setMode('full')}catch(e){}
function openTarget(){const el=location.hash&&document.getElementById(decodeURIComponent(location.hash.slice(1)));const d=el&&el.closest('details.deep');if(d&&!d.open){d.open=true;el.scrollIntoView()}}
addEventListener('hashchange',openTarget);openTarget();
let deepState=[];
addEventListener('beforeprint',()=>{deepState=deep.map(d=>[d,d.open]);deep.forEach(d=>d.open=true)});
addEventListener('afterprint',()=>deepState.forEach(([d,open])=>d.open=open));
