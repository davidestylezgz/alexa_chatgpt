from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
import ask_sdk_core.utils as ask_utils
import requests
import logging
import json
import os
import uuid
import time

# Configuración de n8n
N8N_WEBHOOK_URL = os.environ.get('N8N_WEBHOOK_URL', 'http://davepi.duckdns.org:5678/webhook-test/alexa-chat')
N8N_API_KEY = os.environ.get('N8N_API_KEY', '')  # Si usas autenticación

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class LaunchRequestHandler(AbstractRequestHandler):
    """Handler for Skill Launch."""
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        speak_output = "Chat G.P.T. mode activated"
        
        session_attr = handler_input.attributes_manager.session_attributes
        session_attr["chat_history"] = []
        session_attr["session_id"] = generate_session_id()
        
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class GptQueryIntentHandler(AbstractRequestHandler):
    """Handler for Gpt Query Intent - Integrado con n8n."""
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GptQueryIntent")(handler_input)

    def handle(self, handler_input):
        query = handler_input.request_envelope.request.intent.slots["query"].value
        
        session_attr = handler_input.attributes_manager.session_attributes
        if "chat_history" not in session_attr:
            session_attr["chat_history"] = []
            session_attr["session_id"] = generate_session_id()
        
        # Enviar consulta a n8n workflow
        response_data = send_to_n8n_workflow(
            query=query,
            chat_history=session_attr["chat_history"],
            session_id=session_attr.get("session_id")
        )
        
        if response_data and response_data.get('success'):
            response_text = response_data.get('response', 'Lo siento, no pude generar una respuesta.')
            followup_questions = response_data.get('followup_questions', [])
            
            # Actualizar historial de conversación - SOLO con el texto de respuesta
            session_attr["chat_history"].append((query, response_text))
            
            # Mantener solo las últimas 10 conversaciones para evitar problemas de memoria
            if len(session_attr["chat_history"]) > 10:
                session_attr["chat_history"] = session_attr["chat_history"][-10:]
            
            # Formatear respuesta con preguntas de seguimiento
            formatted_response = format_response_with_followups(response_text, followup_questions)
            
            reprompt_text = "¿En qué más puedo ayudarte? Puedes hacer otra pregunta o decir 'stop' para salir."
            
            return (
                handler_input.response_builder
                    .speak(formatted_response)
                    .ask(reprompt_text)
                    .response
            )
        else:
            error_message = "Lo siento, hubo un problema procesando tu consulta. Intenta de nuevo."
            logger.error(f"Error en respuesta de n8n: {response_data}")
            return (
                handler_input.response_builder
                    .speak(error_message)
                    .ask(error_message)
                    .response
            )

class ClearContextIntentHandler(AbstractRequestHandler):
    """Handler for clearing conversation context."""
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("ClearContextIntent")(handler_input)

    def handle(self, handler_input):
        session_attr = handler_input.attributes_manager.session_attributes
        session_attr["chat_history"] = []
        session_attr["session_id"] = generate_session_id()
        
        speak_output = "He limpiado nuestro historial de conversación. ¿De qué te gustaría hablar?"
        
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""
    def can_handle(self, handler_input):
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        speak_output = "Leaving Chat G.P.T. mode"
        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Generic error handling to capture any syntax or routing errors."""
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error(exception, exc_info=True)
        speak_output = "Lo siento, tuve un problema procesando tu solicitud. Intenta de nuevo."
        
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

def generate_session_id():
    """Genera un ID único para la sesión"""
    return str(uuid.uuid4())

def send_to_n8n_workflow(query, chat_history, session_id):
    """Envía la consulta al workflow de n8n y recibe la respuesta procesada"""
    try:
        headers = {
            "Content-Type": "application/json"
        }
        
        # Añadir autenticación si es necesaria
        if N8N_API_KEY:
            headers["Authorization"] = f"Bearer {N8N_API_KEY}"
        
        # Formatear el historial para envío - solo las últimas 5 interacciones
        formatted_history = []
        for i, (q, a) in enumerate(chat_history[-5:]):
            formatted_history.append({
                "question": q,
                "answer": a,
                "index": i
            })
        
        payload = {
            "query": query,
            "chat_history": formatted_history,
            "session_id": session_id,
            "timestamp": int(time.time()),
            "source": "alexa_skill"
        }
        
        logger.info(f"Enviando a n8n: {json.dumps(payload, indent=2)}")
        
        response = requests.post(
            N8N_WEBHOOK_URL,
            headers=headers,
            json=payload,
            timeout=15  # Aumentado el timeout
        )
        
        logger.info(f"Status code de n8n: {response.status_code}")
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                logger.info(f"Respuesta de n8n: {json.dumps(response_data, indent=2)}")
                return response_data
            except json.JSONDecodeError as e:
                logger.error(f"Error decodificando JSON de n8n: {e}")
                logger.error(f"Respuesta cruda: {response.text}")
                return {"success": False, "error": "Invalid JSON response"}
        else:
            logger.error(f"Error HTTP de n8n: {response.status_code}")
            logger.error(f"Respuesta: {response.text}")
            return {"success": False, "error": f"HTTP {response.status_code}"}
            
    except requests.exceptions.Timeout:
        logger.error("Timeout al conectar con n8n")
        return {"success": False, "error": "Timeout"}
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Error de conexión con n8n: {str(e)}")
        return {"success": False, "error": "Connection error"}
    except Exception as e:
        logger.error(f"Error inesperado enviando a n8n: {str(e)}")
        return {"success": False, "error": str(e)}

def format_response_with_followups(response_text, followup_questions):
    """Formatea la respuesta con preguntas de seguimiento"""
    # Limpiar el texto de respuesta de posibles caracteres problemáticos para SSML
    formatted_response = response_text.strip()
    
    # Asegurarse de que las preguntas de seguimiento sean válidas
    if followup_questions and isinstance(followup_questions, list) and len(followup_questions) > 0:
        # Filtrar preguntas vacías o inválidas
        valid_questions = [q.strip() for q in followup_questions if q and isinstance(q, str) and q.strip()]
        
        if valid_questions:
            formatted_response += " <break time=\"0.5s\"/> "
            formatted_response += "Podrías preguntar: "
            
            if len(valid_questions) > 1:
                formatted_response += ", ".join([f"'{q}'" for q in valid_questions[:-1]])
                formatted_response += f", o '{valid_questions[-1]}'"
            else:
                formatted_response += f"'{valid_questions[0]}'"
                
            formatted_response += ". <break time=\"0.5s\"/> ¿Qué te gustaría saber?"
    
    return formatted_response

# Configuración del Skill Builder
sb = SkillBuilder()

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(GptQueryIntentHandler())
sb.add_request_handler(ClearContextIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
