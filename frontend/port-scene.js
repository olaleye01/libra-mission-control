/* A self-contained port diorama. It displays no shipment or tracking information. */
(() => {
  'use strict';
  const scene=document.querySelector('.port-scene');
  const canvas=scene?.querySelector('.port-canvas');
  if(!scene||!canvas)return;
  const auth=document.querySelector('#auth-screen');
  const toggle=document.querySelector('#port-motion');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let paused=reduced.matches,visible=false,frameId=0,last=0,elapsed=0,width=0,height=0,failed=false;
  let refresh=()=>{};
  const syncPause=()=>{
    scene.classList.toggle('scene-paused',paused);
    if(toggle){
      toggle.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paused?'<path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none"/>':'<path d="M8 5v14M16 5v14"/>'}</svg>`;
      toggle.title=paused?'Play animation':'Pause animation';
      toggle.setAttribute('aria-label',paused?'Play port animation':'Pause port animation');
      toggle.setAttribute('aria-pressed',String(paused));
    }
  };
  toggle?.addEventListener('click',()=>{paused=!paused;syncPause();refresh();});
  reduced.addEventListener('change',()=>{paused=reduced.matches;syncPause();refresh();});
  syncPause();
  let gl;
  try{gl=canvas.getContext('webgl',{alpha:true,antialias:true,powerPreference:'low-power',premultipliedAlpha:true});}catch{return;}
  if(!gl)return;
  const vertex=`attribute vec3 aPosition; attribute vec3 aNormal; attribute vec3 aColor; attribute float aGlow; attribute float aAlpha;
  uniform mat4 uViewProjection; varying vec3 vColor; varying vec3 vNormal; varying vec3 vPosition; varying float vGlow; varying float vAlpha;
  void main(){vColor=aColor;vNormal=aNormal;vPosition=aPosition;vGlow=aGlow;vAlpha=aAlpha;gl_Position=uViewProjection*vec4(aPosition,1.0);}`;
  const fragment=`precision mediump float; varying vec3 vColor; varying vec3 vNormal; varying vec3 vPosition; varying float vGlow; varying float vAlpha;
  void main(){vec3 n=normalize(vNormal); vec3 light=normalize(vec3(-0.5,1.0,0.7)); float diffuse=max(dot(n,light),0.0);
    vec3 color=vColor*(0.40+0.68*diffuse); color+=vColor*vGlow;
    float fog=clamp((length(vPosition.xz)-5.0)*0.035,0.0,0.22); color=mix(color,vec3(0.025,0.065,0.085),fog);
    gl_FragColor=vec4(color*vAlpha,vAlpha);}`;
  const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error('Port shader unavailable');return s;};
  let program;
  try {program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))return;}catch{return;}
  gl.useProgram(program);
  const attributes=[['aPosition',3],['aNormal',3],['aColor',3],['aGlow',1],['aAlpha',1]];
  let offset=0;
  const layout=attributes.map(([name,size])=>{const item={location:gl.getAttribLocation(program,name),size,offset:offset*4};offset+=size;return item;});
  const matrixLocation=gl.getUniformLocation(program,'uViewProjection');
  const staticBuffer=gl.createBuffer(),dynamicBuffer=gl.createBuffer();
  const C={water:'#0b2732',waterLine:'#19434e',base:'#18313b',edge:'#365662',surface:'#56717b',pale:'#c9d9d9',silver:'#9db8bc',dark:'#102b37',cyan:'#68d3e0',cyanDark:'#367e8b',gold:'#dfb563',goldSide:'#c59546',tire:'#06141c',glass:'#1b4d5b',road:'#233c47',stripe:'#8ca2a6'};
  const color=hex=>{const n=parseInt(hex.slice(1),16);return [(n>>16)/255,((n>>8)&255)/255,(n&255)/255];};
  const rgb={};Object.entries(C).forEach(([k,v])=>rgb[k]=color(v));
  let target=[];
  const triangle=(a,b,c,n,col,glow=0,alpha=1)=>{for(const p of [a,b,c])target.push(...p,...n,...col,glow,alpha);};
  const quad=(a,b,c,d,n,col,glow=0,alpha=1)=>{triangle(a,b,c,n,col,glow,alpha);triangle(a,c,d,n,col,glow,alpha);};
  const box=(x,y,z,w,h,d,col,glow=0,alpha=1)=>{
    const a=x-w/2,b=x+w/2,c=y-h/2,e=y+h/2,f=z-d/2,g=z+d/2;
    quad([a,e,f],[a,e,g],[b,e,g],[b,e,f],[0,1,0],col,glow,alpha);
    quad([a,c,g],[a,e,g],[a,e,f],[a,c,f],[-1,0,0],col,glow,alpha);
    quad([b,c,f],[b,e,f],[b,e,g],[b,c,g],[1,0,0],col,glow,alpha);
    quad([a,c,f],[a,e,f],[b,e,f],[b,c,f],[0,0,-1],col,glow,alpha);
    quad([b,c,g],[b,e,g],[a,e,g],[a,c,g],[0,0,1],col,glow,alpha);
  };
  const beam=(a,b,thick,col,glow=0)=>{
    const v=b.map((n,i)=>n-a[i]),length=Math.hypot(...v),u=v.map(n=>n/length);
    let side=Math.abs(u[1])>.9?[1,0,0]:[-u[2],0,u[0]];
    const sl=Math.hypot(...side);side=side.map(n=>n/sl*thick/2);
    const other=[u[1]*side[2]-u[2]*side[1],u[2]*side[0]-u[0]*side[2],u[0]*side[1]-u[1]*side[0]];
    const points=p=>[[...p.map((n,i)=>n+side[i]+other[i])],[...p.map((n,i)=>n-side[i]+other[i])],[...p.map((n,i)=>n-side[i]-other[i])],[...p.map((n,i)=>n+side[i]-other[i])]];
    const aa=points(a),bb=points(b);
    for(let i=0;i<4;i++){const j=(i+1)%4;const n=[(aa[i][0]+aa[j][0])/2-a[0],(aa[i][1]+aa[j][1])/2-a[1],(aa[i][2]+aa[j][2])/2-a[2]];quad(aa[i],aa[j],bb[j],bb[i],n,col,glow);}
  };
  const cylinder=(x,y,z,r,length,col,axis='x',alpha=1)=>{
    const sides=10;
    for(let i=0;i<sides;i++){
      const a=i*Math.PI*2/sides,b=(i+1)*Math.PI*2/sides;
      const point=(angle,end)=>axis==='x'?[x+end,y+Math.cos(angle)*r,z+Math.sin(angle)*r]:[x+Math.cos(angle)*r,y+end,z+Math.sin(angle)*r];
      const n=axis==='x'?[0,Math.cos((a+b)/2),Math.sin((a+b)/2)]:[Math.cos((a+b)/2),0,Math.sin((a+b)/2)];
      quad(point(a,-length/2),point(b,-length/2),point(b,length/2),point(a,length/2),n,col,0,alpha);
      const center=axis==='x'?[x+length/2,y,z]:[x,y+length/2,z];
      triangle(center,point(a,length/2),point(b,length/2),axis==='x'?[1,0,0]:[0,1,0],col,0,alpha);
    }
  };
  const container=(x,y,z,col=rgb.silver,alpha=1)=>{
    box(x,y,z,.66,.47,.96,col,0,alpha);
    for(let n=-3;n<=3;n++)box(x+.339,y,z+n*.12,.013,.40,.024,col,0,alpha);
    for(let n=-2;n<=2;n++)box(x+n*.12,y,z+.489,.022,.40,.012,col,0,alpha);
    box(x,y+.243,z,.59,.015,.88,col,0,alpha);
    box(x-.17,y,z+.502,.012,.37,.014,rgb.edge,0,alpha);box(x+.17,y,z+.502,.012,.37,.014,rgb.edge,0,alpha);
  };
  const hull=(x,y,z)=>{
    const shape=[[-.76,-2.95],[.76,-2.95],[.89,2.45],[.42,3.03],[0,3.28],[-.42,3.03],[-.89,2.45]];
    const top=.65+y,bottom=.02+y;
    for(let i=0;i<shape.length;i++){
      const j=(i+1)%shape.length,aa=shape[i],bb=shape[j],dx=bb[0]-aa[0],dz=bb[1]-aa[1];
      quad([x+aa[0],bottom,z+aa[1]],[x+aa[0],top,z+aa[1]],[x+bb[0],top,z+bb[1]],[x+bb[0],bottom,z+bb[1]],[dz,0,-dx],rgb.dark);
      triangle([x,top,z],[x+aa[0],top,z+aa[1]],[x+bb[0],top,z+bb[1]],[0,1,0],rgb.silver);
      beam([x+aa[0],top+.03,z+aa[1]],[x+bb[0],top+.03,z+bb[1]],.025,rgb.cyan,.2);
    }
  };
  const ship=shift=>{
    const x=-3.2+shift[0],z=.15+shift[2];hull(x,0,z);
    box(x,.70,z,.9,.10,5.65,rgb.edge);
    for(const zz of [-1.15,.04,1.23])for(const xx of [-.37,.37])container(x+xx,.99,z+zz,rgb.silver);
    for(const zz of [-1.15,.04])container(x-.37,1.47,z+zz,rgb.pale);
    box(x,1.17,z-2.35,1.13,.86,.72,rgb.pale);
    box(x,1.64,z-2.35,1.30,.17,.87,rgb.silver);
    box(x,1.42,z-1.976,.89,.24,.018,rgb.glass);
    for(const xx of [-.34,0,.34])box(x+xx,1.43,z-1.958,.035,.22,.025,rgb.pale);
    box(x+.29,1.95,z-2.35,.18,.56,.21,rgb.silver);
    beam([x-.30,1.68,z-2.35],[x-.30,2.37,z-2.35],.035,rgb.pale);
    beam([x-.53,2.14,z-2.35],[x-.08,2.14,z-2.35],.022,rgb.pale);
    for(const zz of [-2.7,-1.8,1.95,2.5])for(const xx of [-.76,.76])beam([x+xx,.70,z+zz],[x+xx,.95,z+zz],.017,rgb.pale);
  };
  const truck=(shift,alpha=1)=>{
    const x=2.6,z=2.2+shift;box(x,.53,z,.84,.17,1.75,rgb.edge,0,alpha);
    box(x,.68,z-.67,.78,.55,.59,rgb.pale,0,alpha);
    box(x,.81,z-.98,.65,.23,.012,rgb.glass,0,alpha);box(x,.99,z-.67,.80,.06,.62,rgb.silver,0,alpha);
    for(const xx of [-.44,.44])for(const zz of [-.65,.59])cylinder(x+xx,.43,z+zz,.17,.12,rgb.tire,'x',alpha);
    for(const xx of [-.28,.28])box(x+xx,.58,z-.99,.13,.065,.02,rgb.cyan,.7,alpha);
    box(x,.65,z+.28,.78,.08,1.14,rgb.silver,0,alpha);
  };
  const loader=(x,z,alpha=1)=>{
    box(x,.52,z,.46,.42,.57,rgb.silver,0,alpha);box(x,.82,z-.10,.43,.06,.37,rgb.pale,0,alpha);
    for(const xx of [-.18,.18])box(x+xx,.70,z-.10,.035,.28,.035,rgb.edge,0,alpha);
    for(const xx of [-.27,.27])for(const zz of [-.19,.19])cylinder(x+xx,.39,z+zz,.105,.09,rgb.tire,'x',alpha);
    box(x,.78,z+.31,.40,.76,.055,rgb.edge,0,alpha);box(x,.45,z+.55,.39,.035,.46,rgb.silver,0,alpha);
  };
  target=[];
  // Fade the grid itself into the transparent canvas; an opaque ground slab exposed its rectangular edge.
  const gridAlpha=(x,z)=>{const t=Math.max(0,Math.min(1,(Math.hypot(x,z)-3.6)/5.2));return .48*(1-t*t*(3-2*t));};
  const gridQuad=points=>{
    for(const i of [0,1,2,0,2,3]){const p=points[i];target.push(...p,0,1,0,...rgb.waterLine,0,gridAlpha(p[0],p[2]));}
  };
  for(let n=-9;n<=9;n++){
    for(let x=-10;x<10;x++)gridQuad([[x,-.368,n-.006],[x+1,-.368,n-.006],[x+1,-.368,n+.006],[x,-.368,n+.006]]);
    for(let z=-9;z<9;z++)gridQuad([[n-.006,-.368,z],[n+.006,-.368,z],[n+.006,-.368,z+1],[n-.006,-.368,z+1]]);
  }
  const gridCount=target.length/11;
  box(-4.1,-.23,.3,3.4,.16,8.4,rgb.water);
  for(let n=0;n<11;n++)box(-4.1,-.143,-3.5+n*.68,2.6,.012,.012,rgb.waterLine);
  // Distinct stacked plinths make the infrastructure read as a miniature, rather than a map.
  box(1.55,-.17,.20,7.20,.48,7.40,rgb.base);
  box(1.55,.09,.20,7.08,.10,7.28,rgb.edge);
  box(1.55,.18,.20,6.96,.09,7.16,rgb.surface);
  for(const x of [-1.91,5.01])box(x,.24,.2,.025,.024,7.12,rgb.cyan,.3);
  for(const z of [-3.35,3.75])box(1.55,.24,z,6.92,.024,.025,rgb.cyan,.3);
  for(let n=0;n<8;n++)box(-1.82,.04,-3+n*.86,.11,.15,.20,rgb.dark);
  box(2.6,.238,1.25,1.45,.025,4.7,rgb.road);
  for(let n=0;n<6;n++)box(2.6,.257,.1+n*.54,.035,.012,.23,rgb.stripe);
  for(const x of [1.86,3.34])box(x,.257,1.2,.015,.014,4.6,rgb.silver);
  // The warehouse has a real opening: the truck is occluded by its roof as it enters.
  box(3.1,.29,-1.15,2.65,.09,2.82,rgb.dark);
  box(1.82,1.06,-1.15,.12,1.52,2.82,rgb.silver);
  box(4.38,1.06,-1.15,.12,1.52,2.82,rgb.edge);
  box(3.1,1.06,-2.53,2.65,1.52,.12,rgb.silver);
  box(1.995,1.06,.22,.47,1.52,.12,rgb.silver);
  box(3.81,1.06,.22,1.15,1.52,.12,rgb.silver);
  box(2.60,1.61,.22,.77,.42,.12,rgb.silver);
  box(3.1,1.86,-1.15,2.82,.12,3.0,rgb.pale);
  box(3.1,1.95,-1.15,2.60,.06,2.78,rgb.silver);
  box(3.1,2.00,-1.15,2.35,.035,2.52,rgb.pale);
  for(const z of [-2.0,-1.4,-.8])box(3.1,2.02,z,2.30,.02,.022,rgb.silver);
  box(3.72,2.15,-1.7,.48,.27,.56,rgb.edge);box(3.72,2.30,-1.7,.54,.04,.61,rgb.pale);
  cylinder(2.3,2.14,-1.75,.15,.28,rgb.silver,'y');
  for(const x of [2.65,3.20,3.75])box(x,1.12,.289,.28,.33,.022,rgb.glass);
  box(2.61,1.38,.302,.83,.035,.025,rgb.cyan,.5);
  box(2.61,.25,.52,1.1,.06,.58,rgb.silver);
  // Terminal stack, including one deliberately open slot for the moving gold container.
  for(const x of [-.65,.12,.89])for(const z of [-2.3,-1.2])container(x,.49,z,rgb.silver);
  for(const x of [-.65,.12])for(const z of [-2.3,-1.2])container(x,.98,z,rgb.pale);
  container(.12,1.47,-2.3,rgb.silver);
  box(.28,.24,.45,1.2,.022,1.4,rgb.road);
  for(const z of [-.2,1.1])box(.28,.26,z,1.2,.014,.016,rgb.stripe);
  // The tall gantry uses beams, bracing, paired rails and a cross-head.
  for(const x of [-1.30,1.20])for(const z of [-.22,.95]){
    box(x,1.81,z,.14,3.15,.14,rgb.silver);
    box(x,.29,z,.44,.12,.38,rgb.edge);
    box(x,3.39,z,.24,.17,.24,rgb.pale);
  }
  for(const z of [-.22,.95]){
    box(-.73,3.47,z,5.70,.18,.20,rgb.pale);
    box(-.73,3.59,z,5.76,.055,.06,rgb.cyan,.22);
    beam([-1.3,.4,z],[1.2,2.15,z],.065,rgb.edge);
    beam([-1.3,2.15,z],[1.2,.4,z],.065,rgb.edge);
    for(let n=0;n<11;n++)box(-3.40+n*.52,3.47,z,.045,.20,.24,rgb.edge);
  }
  for(const x of [-3.45,-1.3,1.2,2.1])box(x,3.47,.365,.12,.18,1.35,rgb.silver);
  for(let n=0;n<10;n++)box(1.29,.53+n*.25,.98,.04,.035,.30,rgb.pale);
  for(const z of [-2.9,2.95]){
    cylinder(-1.68,.35,z,.065,.25,rgb.dark,'y');
    box(-1.68,.50,z,.18,.05,.11,rgb.silver);
  }
  for(const x of [-1.1,4.65])for(const z of [-2.8,3.2]){
    box(x,.67,z,.035,.80,.035,rgb.edge);box(x,1.08,z,.14,.05,.14,rgb.cyan,.6);
  }
  const staticData=new Float32Array(target),staticCount=target.length/11;
  gl.bindBuffer(gl.ARRAY_BUFFER,staticBuffer);gl.bufferData(gl.ARRAY_BUFFER,staticData,gl.STATIC_DRAW);
  const normalize=v=>{const l=Math.hypot(...v);return v.map(n=>n/l);};
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
  const multiply=(a,b)=>{const c=new Float32Array(16);for(let col=0;col<4;col++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)c[col*4+row]+=a[k*4+row]*b[col*4+k];return c;};
  const camera=aspect=>{
    const eye=[11,10,13],center=[.15,.75,.15],z=normalize(eye.map((v,i)=>v-center[i])),x=normalize(cross([0,1,0],z)),y=cross(z,x);
    const view=new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);
    // Fit all model bounds, including the approaching ship and elevated crane cargo.
    const bounds=[[-2.08,5.18,-.44,.30,-3.62,4.0],[-4.32,-2.10,.0,2.45,-2.95,4.58],[-3.65,2.24,.20,3.72,-.45,1.18],[1.65,4.58,.20,2.50,-2.72,.62]];
    const projected=[];
    for(const b of bounds)for(const xx of [b[0],b[1]])for(const yy of [b[2],b[3]])for(const zz of [b[4],b[5]]){const point=[xx,yy,zz];projected.push([dot(x,point)-dot(x,eye),dot(y,point)-dot(y,eye)]);}
    const left=Math.min(...projected.map(p=>p[0])),right=Math.max(...projected.map(p=>p[0])),bottom=Math.min(...projected.map(p=>p[1])),top=Math.max(...projected.map(p=>p[1]));
    const vertical=Math.max((top-bottom)*1.13,(right-left)*1.13/aspect),horizontal=vertical*aspect,near=.1,far=60;
    const cx=(left+right)/2,cy=(bottom+top)/2;
    const projection=new Float32Array([2/horizontal,0,0,0,0,2/vertical,0,0,0,0,-2/(far-near),0,-2*cx/horizontal,-2*cy/vertical,-(far+near)/(far-near),1]);
    return multiply(projection,view);
  };
  const mix=(a,b,t)=>a.map((n,i)=>n+(b[i]-n)*t);
  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const between=(p,a,b)=>clamp((p-a)/(b-a));
  const bind=buffer=>{gl.bindBuffer(gl.ARRAY_BUFFER,buffer);for(const a of layout){gl.enableVertexAttribArray(a.location);gl.vertexAttribPointer(a.location,a.size,gl.FLOAT,false,44,a.offset);}};
  function draw(seconds){
    const rect=canvas.getBoundingClientRect();
    if(rect.width<1||rect.height<1)return;
    const dpr=Math.min(devicePixelRatio||1,2),w=Math.round(rect.width*dpr),h=Math.round(rect.height*dpr);
    if(w!==width||h!==height){canvas.width=width=w;canvas.height=height=h;gl.viewport(0,0,w,h);}
    gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
    gl.uniformMatrix4fv(matrixLocation,false,camera(rect.width/rect.height));bind(staticBuffer);
    gl.depthMask(false);gl.drawArrays(gl.TRIANGLES,0,gridCount);gl.depthMask(true);
    gl.drawArrays(gl.TRIANGLES,gridCount,staticCount-gridCount);
    const p=(seconds%24)/24;
    let shift=[0,0,0];
    if(p<.18)shift=mix([-.15,0,1.1],[0,0,0],between(p,0,.18));
    else if(p>.82)shift=mix([0,0,0],[-.15,0,1.1],between(p,.82,1));
    target=[];ship(shift);
    const points=[[0,[-2.98,1.47,1.29]],[.18,[-2.83,1.47,.19]],[.25,[-2.83,1.47,.19]],[.33,[-2.83,2.80,.19]],[.42,[.28,2.80,.45]],[.50,[.28,.50,.45]],[.56,[2.6,.925,2.48]],[.78,[2.6,.925,-.08]],[.819,[2.6,.925,-.08]]];
    let cargo=points[0][1];
    for(let i=1;i<points.length;i++){if(p<=points[i][0]){cargo=mix(points[i-1][1],points[i][1],between(p,points[i-1][0],points[i][0]));break;}cargo=points[i][1];}
    let alpha=1;
    if(p>.81&&p<.82)alpha=1-between(p,.81,.82);
    if(p>=.82){cargo=mix([-2.83,1.47,.19],[-2.98,1.47,1.29],between(p,.82,1));alpha=p<.98?0:between(p,.98,1);}
    container(...cargo,rgb.gold,alpha);
    const drive=p<.56?0:p<=.78?-2.56*between(p,.56,.78):p<.82?-2.56:0;
    truck(drive,p>.81&&p<.82?1-between(p,.81,.82):p>=.82&&p<.98?0:p>=.98?between(p,.98,1):1);
    if(p>=.47&&p<.59){const l=mix([.28,.45],[2.6,2.48],between(p,.50,.56));loader(l[0]-.43,l[1]-.18,clamp((p-.47)/.03)*clamp((.59-p)/.03));}
    if(p>=.25&&p<.51){
      box(cargo[0],3.43,cargo[2],.31,.16,.34,rgb.edge);box(cargo[0],3.52,cargo[2],.39,.06,.40,rgb.pale);
      for(const xx of [-.23,.23])beam([cargo[0]+xx,3.35,cargo[2]],[cargo[0]+xx,cargo[1]+.24,cargo[2]],.012,rgb.silver);
      box(cargo[0],cargo[1]+.27,cargo[2],.60,.055,.80,rgb.dark);
    }
    gl.bindBuffer(gl.ARRAY_BUFFER,dynamicBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(target),gl.DYNAMIC_DRAW);bind(dynamicBuffer);gl.drawArrays(gl.TRIANGLES,0,target.length/11);
    if(gl.getError()!==gl.NO_ERROR)throw new Error('Port rendering unavailable');
    scene.classList.add('canvas-ready');
  }
  const render=seconds=>{try{draw(seconds);}catch{failed=true;scene.classList.remove('canvas-ready');}};
  function animate(time){frameId=0;if(failed||!visible||document.hidden||auth?.hidden)return;const delta=last?Math.min(time-last,80):0;last=time;if(!paused)elapsed+=delta;render(paused&&reduced.matches?11.8:elapsed/1000);if(!failed&&!paused)frameId=requestAnimationFrame(animate);}
  refresh=()=>{
    if(frameId)cancelAnimationFrame(frameId);frameId=0;last=0;
    const active=!failed&&visible&&!document.hidden&&!auth?.hidden;
    if(active){render(paused&&reduced.matches?11.8:elapsed/1000);if(!failed&&!paused)frameId=requestAnimationFrame(animate);}
  };
  document.addEventListener('visibilitychange',refresh);
  new ResizeObserver(refresh).observe(canvas);
  if(auth)new MutationObserver(refresh).observe(auth,{attributes:true,attributeFilter:['hidden']});
  new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;refresh();},{threshold:.05}).observe(scene);
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();failed=true;if(frameId)cancelAnimationFrame(frameId);frameId=0;scene.classList.remove('canvas-ready');});
  refresh();
})();
