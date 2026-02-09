import React, {useEffect, useState} from 'react'

export default function App(){
  const [msg, setMsg] = useState('')

  useEffect(()=>{
    fetch('/api/hello')
      .then(r=>r.json())
      .then(d=>setMsg(d.message))
      .catch(()=>setMsg('Backend unreachable'))
  },[])

  return (
    <div style={{fontFamily:'Arial',padding:20}}>
      <h1>PayLens</h1>
      <p>{msg}</p>
    </div>
  )
}
