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
            
            # Actualizar historial de conversación
            session_attr["chat_history"].append((query, response_text))
            session_attr["followup_questions"] = followup_questions
            
            # Formatear respuesta con preguntas de seguimiento
            formatted_response = format_response_with_followups(response_text, followup_questions)
            
            reprompt_text = "¿En qué más puedo ayudarte? Puedes hacer otra pregunta o decir 'stop' para salir."
            if followup_questions:
                reprompt_text = "Puedes hacer otra pregunta, o decir 'stop' para salir."
            
            return (
                handler_input.response_builder
                    .speak(formatted_response)
                    .ask(reprompt_text)
                    .response
            )
        else:
            error_message = "Lo siento, hubo un problema procesando tu consulta. Intenta de nuevo."
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
    import uuid
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
        
        payload = {
            "query": query,
            "chat_history": chat_history[-10:],  # Últimas 10 interacciones
            "session_id": session_id,
            "timestamp": int(time.time()),
            "source": "alexa_skill"
        }
        
        logger.info(f"Enviando a n8n: {payload}")
        
        response = requests.post(
            N8N_WEBHOOK_URL,
            headers=headers,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            response_data = response.json()
            logger.info(f"Respuesta de n8n: {response_data}")
            return response_data
        else:
            logger.error(f"Error de n8n: {response.status_code} - {response.text}")
            return {"success": False, "error": f"HTTP {response.status_code}"}
            
    except requests.exceptions.Timeout:
        logger.error("Timeout al conectar con n8n")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        logger.error(f"Error enviando a n8n: {str(e)}")
        return {"success": False, "error": str(e)}

def format_response_with_followups(response_text, followup_questions):
    """Formatea la respuesta con preguntas de seguimiento"""
    formatted_response = response_text
    
    if followup_questions and len(followup_questions) > 0:
        formatted_response += " <break time=\"0.5s\"/> "
        formatted_response += "Podrías preguntar: "
        
        if len(followup_questions) > 1:
            formatted_response += ", ".join([f"'{q}'" for q in followup_questions[:-1]])
            formatted_response += f", o '{followup_questions[-1]}'"
        else:
            formatted_response += f"'{followup_questions[0]}'"
            
        formatted_response += ". <break time=\"0.5s\"/> ¿Qué te gustaría saber?"
    
    return formatted_response

import time

# Configuración del Skill Builder
sb = SkillBuilder()

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(GptQueryIntentHandler())
sb.add_request_handler(ClearContextIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()