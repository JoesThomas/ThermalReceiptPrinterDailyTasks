'use strict';
(() => {
 const list=document.querySelector('[data-household-people]'),template=document.querySelector('#household-person-template');
 if(!list||!template)return;
 let index=Math.max(-1,...Array.from(list.querySelectorAll('[name=person_index]'),n=>Number(n.value)))+1;
 document.querySelector('[data-add-person]')?.addEventListener('click',()=>{
   if(list.querySelectorAll('fieldset').length>=20)return;
   const html=template.innerHTML.replaceAll('__index__',String(index++)).replaceAll('__number__',String(list.querySelectorAll('fieldset').length+1));
   const holder=document.createElement('template');holder.innerHTML=html;list.append(holder.content.cloneNode(true));
   list.lastElementChild.querySelector('input:not([type=hidden])')?.focus();
 });
 list.addEventListener('click',event=>{if(event.target.closest('[data-remove-person]')&&list.querySelectorAll('fieldset').length>1)event.target.closest('fieldset').remove();});
})();
