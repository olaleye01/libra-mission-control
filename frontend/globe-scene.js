/* Illustrative shipping routes. This renderer never reads shipment or vessel-position data. */
(() => {
  'use strict';

  const TAU=Math.PI*2,rad=value=>value*Math.PI/180;
  const add=(a,b)=>a.map((n,i)=>n+b[i]);
  const scale=(a,s)=>a.map(n=>n*s);
  const dot=(a,b)=>a.reduce((sum,n,i)=>sum+n*b[i],0);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const normal=a=>{const length=Math.hypot(...a)||1;return a.map(n=>n/length);};
  const mix=(a,b,t)=>a.map((n,i)=>n+(b[i]-n)*t);
  const geo=(lat,lon)=>[Math.cos(rad(lat))*Math.sin(rad(lon)),Math.sin(rad(lat)),Math.cos(rad(lat))*Math.cos(rad(lon))];
  const multiply=(a,b)=>{
    const out=new Float32Array(16);
    for(let col=0;col<4;col++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)out[col*4+row]+=a[k*4+row]*b[col*4+k];
    return out;
  };
  const rotation=(pitch,yaw)=>{
    const c=Math.cos(yaw),s=Math.sin(yaw),a=Math.cos(pitch),b=Math.sin(pitch);
    return new Float32Array([c,b*s,-a*s,0,0,a,b,0,s,-b*c,a*c,0,0,0,0,1]);
  };
  const objectMatrix=(right,up,forward,position)=>new Float32Array([
    ...right,0,...up,0,...forward,0,...position,1
  ]);
  const sphere=()=>{
    const positions=[],steps=96,bands=48;
    const point=(x,y)=>{
      const latitude=-Math.PI/2+y/bands*Math.PI,longitude=-Math.PI+x/steps*TAU;
      return [Math.cos(latitude)*Math.sin(longitude),Math.sin(latitude),Math.cos(latitude)*Math.cos(longitude),x/steps,y/bands];
    };
    for(let y=0;y<bands;y++)for(let x=0;x<steps;x++){
      const a=point(x,y),b=point(x+1,y),c=point(x+1,y+1),d=point(x,y+1);
      positions.push(...a,...b,...c,...a,...c,...d);
    }
    return new Float32Array(positions);
  };

  // Ocean-oriented schematic corridors, not observations of any client shipment.
  const corridors=[
    {points:[[51.9,4.5],[49,-12],[30,-19],[12,-17],[6.4,3.4]],duration:72,phase:.45},
    {points:[[39,-74],[30,-60],[18,-38],[6.4,3.4]],duration:86,phase:.55},
    {points:[[1.3,103.8],[2.5,101],[5.8,96],[0,86],[-20,63],[-38,23],[-34,11],[-12,-2],[6.4,3.4]],duration:98,phase:.76},
    {points:[[35,15],[37.4,8],[37.1,-1],[35.8,-6],[24,-20],[9,-15],[6.4,3.4]],duration:79,phase:.2}
  ];
  function route(definition){
    const anchors=definition.points.map(p=>geo(...p));
    const lengths=anchors.slice(1).map((p,i)=>Math.acos(Math.max(-1,Math.min(1,dot(anchors[i],p)))));
    const total=lengths.reduce((sum,n)=>sum+n,0),points=[],distances=[];
    for(let i=0;i<=180;i++){
      const distance=total*i/180;
      let segment=0,previous=0;
      while(segment<lengths.length-1&&distance>previous+lengths[segment])previous+=lengths[segment++];
      const t=(distance-previous)/lengths[segment],angle=lengths[segment],a=anchors[segment],b=anchors[segment+1];
      const direction=angle<.0001?normal(mix(a,b,t)):add(scale(a,Math.sin((1-t)*angle)/Math.sin(angle)),scale(b,Math.sin(t*angle)/Math.sin(angle)));
      points.push(scale(normal(direction),1.014+.055*Math.sin(Math.PI*i/180)));
      distances.push(distance);
    }
    return {...definition,points,distances};
  }
  const routes=corridors.map(route);
  function ribbons(width){
    const data=[];
    for(const path of routes)for(let i=0;i<path.points.length-1;i++){
      const a=path.points[i],b=path.points[i+1],side=scale(normal(cross(normal(add(a,b)),normal(add(b,scale(a,-1))))),width/2);
      const aa=add(a,side),ab=add(a,scale(side,-1)),ba=add(b,side),bb=add(b,scale(side,-1));
      for(const [point,distance] of [[aa,path.distances[i]],[ab,path.distances[i]],[bb,path.distances[i+1]],[aa,path.distances[i]],[bb,path.distances[i+1]],[ba,path.distances[i+1]]])data.push(...point,distance);
    }
    return new Float32Array(data);
  }
  function ship(){
    const data=[];
    const tri=(a,b,c,n,color)=>{for(const p of [a,b,c])data.push(...p,...n,...color);};
    const quad=(a,b,c,d,n,color)=>{tri(a,b,c,n,color);tri(a,c,d,n,color);};
    const box=(x,y,z,w,h,d,color)=>{
      const a=x-w/2,b=x+w/2,c=y-h/2,e=y+h/2,f=z-d/2,g=z+d/2;
      quad([a,e,f],[a,e,g],[b,e,g],[b,e,f],[0,1,0],color);
      quad([a,c,g],[a,e,g],[a,e,f],[a,c,f],[-1,0,0],color);
      quad([b,c,f],[b,e,f],[b,e,g],[b,c,g],[1,0,0],color);
      quad([a,c,f],[a,e,f],[b,e,f],[b,c,f],[0,0,-1],color);
      quad([b,c,g],[b,e,g],[a,e,g],[a,c,g],[0,0,1],color);
    };
    const outline=[[-.036,-.10],[.036,-.10],[.043,.055],[.025,.09],[0,.115],[-.025,.09],[-.043,.055]];
    for(let i=0;i<outline.length;i++){
      const j=(i+1)%outline.length,a=outline[i],b=outline[j],n=normal([b[1]-a[1],0,a[0]-b[0]]);
      quad([a[0],.003,a[1]],[a[0],.026,a[1]],[b[0],.026,b[1]],[b[0],.003,b[1]],n,[.13,.22,.29]);
      tri([0,.027,0],[a[0],.027,a[1]],[b[0],.027,b[1]],[0,1,0],[.88,.93,.94]);
    }
    box(0,.044,-.07,.065,.032,.043,[.95,.97,.96]);
    box(0,.059,-.047,.052,.011,.005,[.13,.37,.48]);
    box(.017,.072,-.075,.014,.027,.014,[.85,.9,.91]);
    for(const x of [-.018,.018])for(const z of [-.018,.032,.072])box(x,.04,z,.029,.022,.036,z>.06?[.78,.32,.19]:x<0?[.15,.43,.62]:[.9,.67,.26]);
    return new Float32Array(data);
  }
  function markers(){
    const data=[],ports=[[6.4,3.4],[51.9,4.5],[39,-74],[1.3,103.8],[35,15]];
    for(let i=0;i<ports.length;i++){
      const up=geo(...ports[i]),right=normal(cross([0,1,0],up)),forward=normal(cross(up,right));
      const radius=i===0?.041:.023;
      const point=(angle,r)=>add(scale(up,1.012),add(scale(right,Math.cos(angle)*r),scale(forward,Math.sin(angle)*r)));
      for(let n=0;n<32;n++){
        const a=n*TAU/32,b=(n+1)*TAU/32;
        for(const p of [point(a,radius),point(a,radius*.67),point(b,radius*.67),point(a,radius),point(b,radius*.67),point(b,radius)])data.push(...p,0);
      }
    }
    return new Float32Array(data);
  }
  const sphereData=sphere(),shipData=ship(),markerData=markers();
  const routeLayers=[{data:ribbons(.08),alpha:.18},{data:ribbons(.035),alpha:.36},{data:ribbons(.013),alpha:1}];

  function landTexture(data){
    const canvas=document.createElement('canvas');canvas.width=2048;canvas.height=1024;
    const context=canvas.getContext('2d');
    if(!context)throw new Error('Globe texture unavailable');
    const width=canvas.width,height=canvas.height;
    context.fillStyle='#0c5c87';context.fillRect(0,0,width,height);
    context.strokeStyle='rgba(164,211,225,.23)';context.lineWidth=1;
    for(let lon=-180;lon<=180;lon+=15){const x=(lon+180)/360*width;context.beginPath();context.moveTo(x,0);context.lineTo(x,height);context.stroke();}
    for(let lat=-75;lat<=75;lat+=15){const y=(90-lat)/180*height;context.beginPath();context.moveTo(0,y);context.lineTo(width,y);context.stroke();}
    let polygons=data.polygons;
    if(!Array.isArray(polygons)){
      polygons=[];
      const geometries=data.type==='FeatureCollection'?data.features.map(feature=>feature.geometry):[data.geometry||data];
      for(const geometry of geometries){if(geometry?.type==='Polygon')polygons.push(geometry.coordinates);else if(geometry?.type==='MultiPolygon')polygons.push(...geometry.coordinates);}
    }
    if(!polygons.length)throw new Error('Globe land unavailable');
    const path=(ring,offset)=>{
      const longitudes=ring.map(p=>p[0]),polar=ring.some(p=>p[1]<-88)&&Math.max(...longitudes)-Math.min(...longitudes)>350;
      let previous=null;
      ring.forEach(([lon,lat],index)=>{
        let x=(lon+180)/360*width;
        // Islands straddling the date line must wrap rather than fill across the map.
        if(!polar&&previous!==null){while(x-previous>width/2)x-=width;while(x-previous<-width/2)x+=width;}
        previous=x;const y=(90-lat)/180*height;
        if(index===0)context.moveTo(x+offset,y);else context.lineTo(x+offset,y);
      });
      context.closePath();
    };
    for(const polygon of polygons)for(const offset of [-width,0,width]){
      context.beginPath();for(const ring of polygon)path(ring,offset);
      context.fillStyle='#dce6e7';context.fill('evenodd');
      context.strokeStyle='rgba(227,187,96,.65)';context.lineWidth=1.3;context.stroke();
    }
    return canvas;
  }

  function mount(host){
    const canvas=host?.querySelector('.globe-canvas'),button=host?.querySelector('.globe-motion');
    if(!host||!canvas)return {dispose(){}};
    const reduced=matchMedia('(prefers-reduced-motion: reduce)'),abort=new AbortController();
    let paused=reduced.matches,disposed=false,visible=false,lost=false,failed=false,ready=false;
    let frame=0,lastTick=0,elapsed=0,width=0,height=0,textureCanvas=null,resources=null;
    let gl;
    try{gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:true,powerPreference:'low-power'});}catch{}
    const updateButton=()=>{
      if(!button)return;
      button.hidden=!ready||failed||lost;
      button.disabled=!gl||failed||lost;
      button.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paused?'<path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none"/>':'<path d="M8 5v14M16 5v14"/>'}</svg>`;
      button.title=button.disabled?'Static globe':paused?'Play animation':'Pause animation';
      button.setAttribute('aria-label',button.disabled?'Static shipping globe':paused?'Play globe animation':'Pause globe animation');
      button.setAttribute('aria-pressed',String(paused));
    };
    const stop=()=>{if(frame)cancelAnimationFrame(frame);frame=0;lastTick=0;};
    const unavailable=()=>{failed=true;ready=false;stop();freeResources();host.classList.remove('globe-ready');host.dataset.globeState='unavailable';updateButton();};
    updateButton();
    if(!gl){host.dataset.globeState='unavailable';return {dispose(){disposed=true;abort.abort();}};}

    function createResources(){
      const buffers=[],programs=[],shaders=[];
      const compile=(type,source)=>{
        const shader=gl.createShader(type);shaders.push(shader);gl.shaderSource(shader,source);gl.compileShader(shader);
        if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw new Error('Globe shader unavailable');
        return shader;
      };
      const program=(vertex,fragment,attributes,uniforms)=>{
        const value=gl.createProgram();programs.push(value);
        gl.attachShader(value,compile(gl.VERTEX_SHADER,vertex));gl.attachShader(value,compile(gl.FRAGMENT_SHADER,fragment));
        attributes.forEach((name,index)=>gl.bindAttribLocation(value,index,name));gl.linkProgram(value);
        if(!gl.getProgramParameter(value,gl.LINK_STATUS))throw new Error('Globe program unavailable');
        return {value,attributes:Object.fromEntries(attributes.map(name=>[name,gl.getAttribLocation(value,name)])),uniforms:Object.fromEntries(uniforms.map(name=>[name,gl.getUniformLocation(value,name)]))};
      };
      const buffer=data=>{const value=gl.createBuffer();buffers.push(value);gl.bindBuffer(gl.ARRAY_BUFFER,value);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);return value;};
      resources={buffers,programs,shaders,texture:null};
      resources.sphere=program(`attribute vec3 aPosition;attribute vec2 aUV;uniform mat4 uMatrix;uniform mat4 uModel;varying vec2 vUV;varying vec3 vNormal;
        void main(){vUV=aUV;vNormal=(uModel*vec4(aPosition,0.0)).xyz;gl_Position=uMatrix*vec4(aPosition,1.0);}`,
        `precision mediump float;uniform sampler2D uTexture;varying vec2 vUV;varying vec3 vNormal;
        void main(){vec3 n=normalize(vNormal);vec3 light=normalize(vec3(-.65,.75,1.15));vec3 base=texture2D(uTexture,vUV).rgb;
          float land=step(.55,base.r),diffuse=max(dot(n,light),0.0);vec3 color=base*(.46+.62*diffuse);
          float shine=pow(max(dot(reflect(-light,n),vec3(0.,0.,1.)),0.),35.);color+=vec3(.75,.88,.95)*shine*(1.-land)*.62;
          float rim=pow(1.-max(n.z,0.),3.);color+=vec3(.10,.36,.45)*rim;
          gl_FragColor=vec4(color,1.);}`,
        ['aPosition','aUV'],['uMatrix','uModel','uTexture']);
      resources.lines=program(`attribute vec3 aPosition;attribute float aDistance;uniform mat4 uMatrix;varying float vDistance;
        void main(){vDistance=aDistance;gl_Position=uMatrix*vec4(aPosition,1.0);}`,
        `precision mediump float;uniform float uTime;uniform float uAlpha;uniform float uDashed;varying float vDistance;
        void main(){float phase=fract(vDistance*15.-uTime);float dash=smoothstep(.01,.1,phase)*(1.-smoothstep(.57,.68,phase));
          float alpha=uAlpha*mix(1.,dash,uDashed)*(.91+.09*sin(uTime*6.2831853+vDistance*5.));vec3 color=vec3(1.,.73,.24);
          gl_FragColor=vec4(color*alpha,alpha);}`,
        ['aPosition','aDistance'],['uMatrix','uTime','uAlpha','uDashed']);
      resources.mesh=program(`attribute vec3 aPosition;attribute vec3 aNormal;attribute vec3 aColor;uniform mat4 uMatrix;uniform mat4 uModel;varying vec3 vNormal;varying vec3 vColor;
        void main(){vNormal=(uModel*vec4(aNormal,0.)).xyz;vColor=aColor;gl_Position=uMatrix*vec4(aPosition,1.);}`,
        `precision mediump float;varying vec3 vNormal;varying vec3 vColor;
        void main(){float light=max(dot(normalize(vNormal),normalize(vec3(-.5,.8,1.))),0.);gl_FragColor=vec4(vColor*(.55+.65*light),1.);}`,
        ['aPosition','aNormal','aColor'],['uMatrix','uModel']);
      resources.sphereBuffer=buffer(sphereData);resources.shipBuffer=buffer(shipData);resources.markerBuffer=buffer(markerData);
      resources.routeBuffers=routeLayers.map(layer=>({...layer,buffer:buffer(layer.data)}));
      resources.texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,resources.texture);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,textureCanvas);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    }
    function freeResources(){
      if(!resources)return;
      for(const buffer of resources.buffers)gl.deleteBuffer(buffer);
      for(const program of resources.programs)gl.deleteProgram(program);
      for(const shader of resources.shaders)gl.deleteShader(shader);
      if(resources.texture)gl.deleteTexture(resources.texture);
      resources=null;
    }
    const bind=(program,buffer,attributes,stride)=>{
      gl.useProgram(program.value);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
      // A previous mesh's colour attribute must not retain its shorter ship buffer on the globe pass.
      for(let index=0;index<3;index++)gl.disableVertexAttribArray(index);
      for(const name of ['aPosition','aUV','aDistance','aNormal','aColor']){
        const location=program.attributes[name];if(location===undefined||location<0)continue;
        const attribute=attributes[name];gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,attribute[0],gl.FLOAT,false,stride*4,attribute[1]*4);
      }
    };
    function draw(){
      if(!resources||disposed||lost)return;
      const rect=canvas.getBoundingClientRect();if(rect.width<1||rect.height<1)return;
      const dpr=Math.min(devicePixelRatio||1,1.5),w=Math.round(rect.width*dpr),h=Math.round(rect.height*dpr);
      if(w!==width||h!==height){canvas.width=width=w;canvas.height=height=h;gl.viewport(0,0,w,h);}
      const aspect=rect.width/rect.height,vertical=Math.max(2.25,2.25/aspect);
      const projection=new Float32Array([2/(vertical*aspect),0,0,0,0,2/vertical,0,0,0,0,-1/3,0,0,-.015,0,1]);
      const earth=rotation(rad(12),rad(-12)+elapsed*TAU/180),matrix=multiply(projection,earth);
      gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.depthMask(true);gl.disable(gl.CULL_FACE);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
      const globe=resources.sphere;
      bind(globe,resources.sphereBuffer,{aPosition:[3,0],aUV:[2,3]},5);
      gl.uniformMatrix4fv(globe.uniforms.uMatrix,false,matrix);gl.uniformMatrix4fv(globe.uniforms.uModel,false,earth);
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,resources.texture);gl.uniform1i(globe.uniforms.uTexture,0);
      gl.drawArrays(gl.TRIANGLES,0,sphereData.length/5);
      const lines=resources.lines;
      gl.depthMask(false);
      for(const layer of resources.routeBuffers){
        bind(lines,layer.buffer,{aPosition:[3,0],aDistance:[1,3]},4);
        gl.uniformMatrix4fv(lines.uniforms.uMatrix,false,matrix);gl.uniform1f(lines.uniforms.uTime,(elapsed*.16)%1);gl.uniform1f(lines.uniforms.uAlpha,layer.alpha);gl.uniform1f(lines.uniforms.uDashed,1);
        gl.drawArrays(gl.TRIANGLES,0,layer.data.length/4);
      }
      bind(lines,resources.markerBuffer,{aPosition:[3,0],aDistance:[1,3]},4);
      gl.uniformMatrix4fv(lines.uniforms.uMatrix,false,matrix);gl.uniform1f(lines.uniforms.uTime,(elapsed*.16)%1);gl.uniform1f(lines.uniforms.uAlpha,.96);gl.uniform1f(lines.uniforms.uDashed,0);
      gl.drawArrays(gl.TRIANGLES,0,markerData.length/4);gl.depthMask(true);
      const mesh=resources.mesh;
      bind(mesh,resources.shipBuffer,{aPosition:[3,0],aNormal:[3,3],aColor:[3,6]},9);
      for(const path of routes){
        const progress=(path.phase+elapsed/path.duration)%1,index=progress*(path.points.length-1),i=Math.min(path.points.length-2,Math.floor(index));
        const position=mix(path.points[i],path.points[i+1],index-i),up=normal(position);
        let forward=normal(add(path.points[Math.min(path.points.length-1,i+2)],scale(path.points[Math.max(0,i-1)],-1)));
        forward=normal(add(forward,scale(up,-dot(forward,up))));
        const right=normal(cross(up,forward)),model=multiply(earth,objectMatrix(right,up,forward,position));
        gl.uniformMatrix4fv(mesh.uniforms.uModel,false,model);gl.uniformMatrix4fv(mesh.uniforms.uMatrix,false,multiply(projection,model));
        gl.drawArrays(gl.TRIANGLES,0,shipData.length/9);
      }
      if(gl.getError()!==gl.NO_ERROR)throw new Error('Globe rendering unavailable');
      if(!ready){ready=true;updateButton();}
      host.classList.add('globe-ready');host.dataset.globeState=paused?'paused':'running';
    }
    const active=()=>!disposed&&!failed&&!lost&&textureCanvas&&visible&&!document.hidden&&host.isConnected;
    const render=()=>{try{draw();}catch{unavailable();}};
    function tick(now){
      frame=0;if(!active()||paused)return;
      if(!lastTick)lastTick=now;
      const delta=now-lastTick;
      if(delta>=1000/30){elapsed+=Math.min(delta,100)/1000;lastTick=now;render();}
      if(active()&&!paused)frame=requestAnimationFrame(tick);
    }
    function refresh(){
      stop();if(!active()){if(ready&&!disposed&&!failed&&!lost)host.dataset.globeState='hidden';return;}
      render();if(active()&&!paused)frame=requestAnimationFrame(tick);
    }
    const motion=()=>{paused=!paused;updateButton();refresh();};
    const preference=()=>{paused=reduced.matches;updateButton();refresh();};
    const contextLost=event=>{event.preventDefault();lost=true;ready=false;stop();host.classList.remove('globe-ready');host.dataset.globeState='unavailable';updateButton();};
    const contextRestored=()=>{
      if(disposed)return;
      lost=false;failed=false;resources=null;
      if(textureCanvas){try{createResources();}catch{unavailable();}}
      updateButton();refresh();
    };
    const resize=new ResizeObserver(refresh);
    const intersection=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;refresh();},{threshold:.01});
    resize.observe(canvas);intersection.observe(host);
    button?.addEventListener('click',motion);reduced.addEventListener('change',preference);
    document.addEventListener('visibilitychange',refresh);canvas.addEventListener('webglcontextlost',contextLost);canvas.addEventListener('webglcontextrestored',contextRestored);
    host.dataset.globeState='loading';
    fetch('/assets/globe-land.json',{signal:abort.signal,credentials:'same-origin'})
      .then(response=>{if(!response.ok)throw new Error('Globe asset unavailable');return response.json();})
      .then(data=>{if(disposed)return;textureCanvas=landTexture(data);createResources();refresh();})
      .catch(error=>{if(!disposed&&error.name!=='AbortError')unavailable();});
    return {
      dispose(){
        if(disposed)return;
        disposed=true;stop();abort.abort();resize.disconnect();intersection.disconnect();
        button?.removeEventListener('click',motion);reduced.removeEventListener('change',preference);
        document.removeEventListener('visibilitychange',refresh);canvas.removeEventListener('webglcontextlost',contextLost);canvas.removeEventListener('webglcontextrestored',contextRestored);
        freeResources();textureCanvas=null;host.classList.remove('globe-ready');host.dataset.globeState='disposed';
      }
    };
  }
  window.LibraGlobe=Object.freeze({mount});
})();
